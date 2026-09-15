# Spec Backend: Arrastre de Saldos de Año Anterior al Flujo de Planificación

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S6-CARRYOVER` |
| **Versión** | 1.0 — 2026-09-14 |
| **Base** | BE-S4 (`backend.02_12` detalle planning) + BE-S5 (`backend.02_15` — sus `payment_date` por cuota son la materia prima). Implementa PQ-1 / mitiga R-S5-1 de BE-S5. NO toca `budget_lines`, la ingesta, la expansión S5, el P&G ni el motor analítico de flujo (`budgetEngine`: otro dominio, tiene su propio `initial_balance`). |
| **Contrato** | Autoridad para `frontend.03_09_Spec_frontend_planning_carryover.md` (FE-S6). |
| **Componentes** | MODIFICAN `app/models/budget/budget.py` (columna), `app/schemas/budget/planning.py` + `budget.py` (respuesta), `app/api/budget/planning.py` (2 endpoints); NUEVO helper de selección de fuente en `app/crud/budget/planning.py` (o `budget.py`, patrón del módulo) |
| **Dependencias** | Cero. ⚠️ **Sin Alembic**: requiere `ALTER` manual en BD existentes (§3.2) |
| **Origen** | Sesión spec-definer 2026-09-14 (continuación de S5): historia "los pagos de años anteriores que se pagan en el año del escenario deben verse en el flujo o lo distorsiona". Decisiones: Q1=3+toggle (arrastre automático N−1, sin ajustes manuales), Q2=1 (flag persistido + dinámica), Q3=2 (N−1, ACTIVE>CLOSED>draft), Q4=4 (columnas fuera-de-año en FE, colapsadas). |

---

> ⚠️ **ENMENDADO por ackend.02_17 §4:** BR-CO-03 complementado con BR-CO-09..11 — el carryover incluye además cuotas de costo DERIVADAS (origin:'cogs') de los ingresos de la fuente.

## 1. Objetivo

Que el Flujo de caja del escenario del año N incluya, cuando el usuario lo active, los **saldos pendientes del escenario de N−1 cuyo cobro/pago cae dentro de N** (p. ej. la cuota 70 % de una importación de diciembre con pago 30 días después). Sin esto, enero y febrero muestran menos movimiento del real y el acumulado de caja sobreestima. El mecanismo es **derivación en lectura**: NUNCA se escriben/copian líneas al escenario.

## 2. Alcance

**Incluye:** columna `include_carryover` en `budgets`; endpoint de consulta de arrastre; endpoint de toggle; reglas de fuente y elegibilidad (BR-CO-01..08); smoke.

**Excluye (v1):** ajustes manuales de saldos (descartado en Q1=3); arrastre de N−2 o selector de años (Q3=2); snapshot/congelación (Q2=1 ⇒ dinámica); saldo inicial de banco para el acumulado (PQ-2); arrastre desde datos REALES (ledger de pagos — dominio analítico, PQ-4); cualquier cambio en Editor/Ejecutiva/P&G/celda/ingesta.

## 3. Modelo de datos

### 3.1 Nueva columna en `budgets` (`app/models/budget/budget.py`)

```python
include_carryover = Column(Boolean, nullable=False, server_default=text("false"))
```

Semántica: preferencia del escenario; cero consumo server-side fuera del endpoint de arrastre (BR-CO-01). Schemas: agregar `include_carryover: bool = False` a `Budget` / `BudgetFull` (y al ítem del listado planning si ya espeja campos del modelo — verificar al implementar); body nuevo `PlanningCarryoverFlag { include_carryover: bool }`.

### 3.2 Migración (manual — convención sin Alembic)

`Base.metadata.create_all` NO altera tablas existentes. Instrucción oficial (documentar en `note.md`/README al implementar):

```sql
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS include_carryover BOOLEAN NOT NULL DEFAULT FALSE;
```

BD de desarrollo puede recrearse. La app NO debe fallar si la columna falta (no aplica — `create_all` solo cubre tablas nuevas; el deploy DEBE correr el ALTER antes).

## 4. Reglas de negocio

- **BR-CO-01 (opt-in puro):** `include_carryover = false` ⇒ el endpoint §5.1 responde `{ enabled: false, source: null, lines: [], unavailable_reason: null }` sin consultar más. La columna no cambia el comportamiento de NINGÚN otro endpoint (regresión estructural nula).
- **BR-CO-02 (fuente):** candidatos = escenarios del mismo ámbito de planificación que el listado `GET /budget/planning/` (misma condición de selección, verificar contra `planning.py`) con `budget_year = N − 1`, excluyendo el propio (`id_budget != id`). Prioridad: `status ACTIVE` > `CLOSED` > `DRAFT`; empates dentro del status: `updated_at DESC`, luego `id_budget DESC` (determinista). Cero candidatos ⇒ `source: null`, `unavailable_reason: "no_source"`.
- **BR-CO-03 (elegibilidad de líneas de la fuente):** solo filas del escenario fuente con `behavior_type == 'fixed'` (las variables no tienen monto materializado) y **fecha efectiva** `coalesce(payment_date, budget_date)` con año == N. Con `payment_date` nula ⇒ la fecha efectiva es `budget_date` (año N−1) ⇒ excluida naturalmente. Se devuelven tanto `income` como `expense` (cobros y pagos de arrastre).
- **BR-CO-04 (dinámica, sin estado):** cada petición recalcula; editar/eliminar el escenario N−1 se refleja en la siguiente lectura de N (decisión Q2=1). Cero escrituras, cero jobs, cero invalidaciones.
- **BR-CO-05 (una sola generación):** jamás se encadena (N no arrastra lo que N−1 arrastró de N−2).
- **BR-CO-06 (no mezclar con fuera-de-año):** las filas PROPIAS de N con fecha efectiva fuera de N NO competen a este endpoint (las resuelve FE-S6 en su pivote, componente C).
- **BR-CO-07 (autorización):** GET ⇒ misma política que leer el detalle; PUT ⇒ misma política que las mutaciones del escenario (patrón celda/upload de FE-S4D §2: sin gate nuevo). 404 del escenario ⇒ `"Budget {id} not found"` (verbatim CRUD existente).
- **BR-CO-08 (idempotencia):** PUT del mismo valor ⇒ 200 sin efecto colateral; nunca valida el año ni la existencia de fuente (el toggle ON con fuente inexistente es estado legal: FE muestra el aviso).

## 5. API (router planning existente, `app/api/budget/planning.py`)

### 5.1 `GET /budget/planning/{id_budget}/carryover` → `PlanningCarryoverResult`

```json
{
  "enabled": true,
  "source": { "id_budget": 12, "budget_name": "Presupuesto 2025", "budget_year": 2025, "status": "active" },
  "lines": [
    { "id_budget_line": 881, "id_cost_center": 4, "line_type": "expense",
      "budget_date": "2025-12-20", "payment_date": "2026-01-19",
      "projected_amount": 700000.0, "description": "Importación dic L4" }
  ],
  "unavailable_reason": null
}
```

- `lines` en orden estable: `coalesce(payment_date, budget_date) ASC, id_budget_line ASC`.
- 404 si `{id_budget}` no existe (aunque esté deshabilitado — la ruta valida pertenencia primero).

### 5.2 `PUT /budget/planning/{id_budget}/carryover` (body `PlanningCarryoverFlag`) → 200 `BudgetFull`

- Actualiza SOLO la columna; devuelve el detalle completo ya con `include_carryover` nuevo (el FE refresca caché con la respuesta, mismo patrón que PUT de línea). 404/422 estándar.

(Sin slash final en ambas; rutas de detalle — convención verificada en `planning.py`.)

## 6. NFR

| ID | Requisito |
|---|---|
| NFR-S6-BE-1 | Costo: ≤2 consultas por GET (fuente + sus líneas filtradas en SQL, no en Python) + 0 en modo deshabilitado. |
| NFR-S6-BE-2 | Regresión: ningún payload existente cambia de forma salvo la clave nueva `include_carryover` (aditiva). |
| NFR-S6-BE-3 | Convenciones: camelCase archivos nuevos si los hay, `db.query` legado, registro explícito de schemas, auth espejo del router planning. |

## 7. Criterios de aceptación (smoke BE)

- **AC-S6-BE-1:** flag OFF ⇒ §5.1 responde `enabled:false, lines:[]` sin SQL adicional observable (log).
- **AC-S6-BE-2:** PUT true ⇒ 200 con `include_carryover:true`; GET siguiente ⇒ `lines` = exactamente las fijas de la fuente con fecha efectiva en N (contra SQL de verificación); `source` con status `active` si lo había.
- **AC-S6-BE-3:** dos escenarios en N−1 (uno `active`, otro `closed`) ⇒ gana `active`; sin active ⇒ `closed`; solo drafts ⇒ el `updated_at` más reciente.
- **AC-S6-BE-4:** ningún escenario en N−1 ⇒ `source:null`, `unavailable_reason:"no_source"`, `enabled` fiel al flag, HTTP 200.
- **AC-S6-BE-5:** arrastre no toca otros endpoints: GET detalle/listado/P&G/Ejecutiva byte-idénticos con flag ON vs OFF (salvo el campo nuevo).
- **AC-S6-BE-6:** cambiar una fecha de pago en N−1 ⇒ el siguiente GET de N refleja el cambio (BR-CO-04, sin cache server).
- **AC-S6-BE-7:** variables y sin fecha efectiva en N ⇒ excluidas (BR-CO-03); una línea de ingreso de N−1 expandida por `line_payment_rules` con cuota en N ⇒ incluida (es fija).
- **AC-S6-BE-8:** PUT 404 literal `"Budget 999999 not found"`; body inválido ⇒ 422.
- **AC-S6-BE-9:** BD recreada con `create_all` + ALTER ⇒ app arranca; columna default false en filas existentes.

## 8. Decision Log (sesión 2026-09-14, interrogatorio al stakeholder)

| ID | Decisión | Origen |
|---|---|---|
| SD6-1 | Arrastre SOLO automático desde N−1; sin captura/ajuste manual | Q1 = opción 3 + variante "toggle opcional" |
| SD6-2 | Flag persistido por escenario + derivación dinámica (sin snapshot) | Q2 = opción 1 |
| SD6-3 | Fuente: N−1 único con prioridad ACTIVE > CLOSED > draft más reciente | Q3 = opción 2 |
| SD6-4 | El arrastre alimenta únicamente el Flujo (FE); jamás causación | Regla sentada en sesión y confirmada en Q4 |
| SD6-5 | FE: columnas "Antes/Después de N" colapsadas por default con chip revelador | Q4 = opción 4 (implementa PQ-1/R-S5-1 de S5) |
| SD6-6 | Sin `initial_balance` en planning v1 (el acumulado arranca en 0 como hoy) | Alcance §2; PQ-2 |

## 9. Riesgos y PQs

- **R-S6-1:** el usuario puede leer el arrastre como dinero "del" escenario ⇒ FE-S6 marca filas con chip `←{N−1}` y nota explícita.
- **R-S6-2:** fuente en DRAFT es volátil (puede borrarse con BE-S4D/02_14) ⇒ mitigado por la prioridad; FE muestra el status de la fuente.
- **R-S6-3:** ALTER manual olvidado en un deploy ⇒ error claro de columna faltante; checklist §10 paso 1 y nota en `note.md`.
- **PQ-1:** saldo inicial de banco estimado en el escenario (acumulado real); **PQ-2:** arrastre multi-año / selector (Q3=3/4); **PQ-3:** overrides por línea; **PQ-4:** arrastre desde saldos REALES del ledger de pagos (`accounts_payable` vigente al 31/12).

## 10. Checklist de implementación

1. ALTER documentado + columna en modelo + schemas (`include_carryover`) ⇒ smoke arranque.
2. Helper de selección de fuente + query de líneas (BR-CO-02/03) en CRUD.
3. GET/PUT `…/carryover` en `planning.py` con auth espejo.
4. Smoke AC-S6-BE-1..9.
5. Congelar contrato ⇒ FE-S6 (`frontend.03_09`).