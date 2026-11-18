# Spec Backend: Saldo Inicial Configurable (Efectivo y Bodega) del Presupuesto de Planificacion

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S7-INITBAL` |
| **Version** | 1.1 -- 2026-10-22 |
| **Base** | BE-S4 (`backend.02_12_Spec_Backend_budgets_planning.md`) + BE-S6 (`backend.02_16_Spec_Backend_planning_carryover.md`, de donde reutiliza el helper de fuente). NO toca la ingesta Excel, la expansion de lineas, el P&G, el motor analitico de flujo (`budgetEngine`) ni el endpoint de lineas de arrastre. |
| **Contrato** | Autoridad para `frontend.03_22_Spec_frontend_budget_planning_initial_balance.md` (FE-S7-INITBAL). |
| **Componentes** | MODIFICAN `app/models/budget/budget.py` (4 columnas), `app/schemas/budget/planning.py` + `app/schemas/__init__.py` (schemas nuevos, registro explicito), `app/crud/budget/planning.py` (helper de contexto), `app/api/budget/planning.py` (2 endpoints + 4 campos opcionales en `POST /upload`). |
| **Dependencias** | Cero nuevas. Sin Alembic: requiere ALTER manual en BD existentes (seccion 3.2). |

> **ENMENDADO v1.1 (2026-10-22) — SD7-10:** en el GET de initial-balance la fuente N−1 se resuelve **SIEMPRE**, independientemente de los modos configurados. Motivo: el FE ofrece "Continuar con el presupuesto meta del año anterior" a partir de `carryover_source`, y condicionar la resolución a que algún modo sea `carryover` producía un falso aviso de bloqueo en un escenario que aún está en ambos `manual` (reporte UX del stakeholder sobre el presupuesto 126). El PUT y el resto del contrato quedan intactos.

---

> Contexto: complementa la decision SD6-6 de BE-S6 ("sin initial_balance en planning v1"): esta feature implementa esa PQ-1 bajo configuracion explicita del usuario, por cada saldo, con modo dinamico (sin snapshot).

## 1. Objetivo

Que al crear un presupuesto (`POST /budget/planning/upload`) y a posteriori desde el editor del escenario, el usuario elija **por separado** para el saldo inicial de efectivo y para el saldo inicial de bodega: (a) continuar con el saldo del presupuesto meta del ano anterior (`carryover`), o (b) ingresarlo manualmente (`manual`). El backend es la fuente de verdad de la configuracion y de los valores manuales, pero **NO deriva el valor por arrastre**: esa derivacion la hace el FE con su motor (`cashFlowPivot`, autoridad de las formulas del flujo y de bodega). El GET de initial-balance entrega **siempre** la resolucion de la fuente N−1 (SD7-10, v1.1), con o sin modos en `carryover`, para que el FE pueda ofertar la eleccion (a) sin falsos avisos.

## 2. Alcance

**Incluye:** 4 columnas en `budgets`; 4 campos multipart opcionales en `POST /upload`; `PUT/GET /budget/planning/{id}/initial-balance`; reglas BR-IB-01..08; smoke.

**Excluye:** computo server-side del valor por arrastre (SA-1); arrastre multi-ano o selector de anos (queda en PQ-2 de BE-S6); snapshot/congelacion de valores; overrides por linea; cambios en Editor/Ejecutiva/P&G/celda; cualquier cambio en el endpoint `/carryover` (feature Ortogonal, BR-IB-07).

## 3. Modelo de datos

### 3.1 Nuevas columnas en `budgets` (`app/models/budget/budget.py`)

```python
initial_cash_mode = Column(String(20), nullable=False, server_default=text("'manual'"))
initial_cash_manual = Column(<mismo tipo de columna que `projected_amount` en budget_lines>, nullable=False, server_default=text("'0'"))
initial_warehouse_mode = Column(String(20), nullable=False, server_default=text("'manual'"))
initial_warehouse_manual = Column(<idem>, nullable=False, server_default=text("'0'"))
```

- Modos validos: `carryover` | `manual` (solo estos, BR-IB-01).
- Schemas: espejar campos en `Budget` / `BudgetFull` y en el item del listado planning si ya espeja campos del modelo (verificar al implementar; aditivo). Schemas nuevos en seccion 5; registrarlos con importacion explicita en `app/schemas/__init__.py` (convencion del modulo, no `*`).

### 3.2 Migracion (manual, convencion sin Alembic)

```sql
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_cash_mode VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_cash_manual NUMERIC(18,2) NOT NULL DEFAULT 0;
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_warehouse_mode VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_warehouse_manual NUMERIC(18,2) NOT NULL DEFAULT 0;
```

Documentar en `note.md`/README al implementar (patron BE-S6 seccion 3.2). El tipo NUMERIC(18,2) es orientativo: usar el mismo tipo real de `projected_amount` en el modelo.

## 4. Reglas de negocio

- **BR-IB-01 (modos):** cada saldo tiene modo independiente. Solo se aceptan `carryover` y `manual` (otro valor => 422). `manual_value` se persiste siempre (default 0) incluso en modo `carryover`; la DEGRADACION al valor manual por ausencia de fuente aplica SOLO cuando el modo ES `carryover` (en `manual` el valor propio es el activo por definicion).
- **BR-IB-02 (creacion):** `POST /budget/planning/upload` acepta 4 campos multipart OPCIONALES: `initial_cash_mode`, `initial_cash_manual`, `initial_warehouse_mode`, `initial_warehouse_manual`. Aplicarlos al Budget creado. Si no llegan (o llegan vacios/omitidos): default `manual`/`0` => clientes y flujos existentes no cambian de comportamiento (regresion cero).
- **BR-IB-03 (PUT):** `PUT /budget/planning/{id}/initial-balance` (body `PlanningInitialBalanceSet`): actualiza SOLO las 4 columnas; devuelve 200 con el `PlanningDetail` completo ya actualizado (mismo patron que el PUT de `/carryover`: la respuesta es el detalle). 404 verbatim `"Budget {id_budget} not found"` (literal del CRUD existente). Idempotente: mismo payload => 200 sin efecto colateral. Autorizacion identica a las mutaciones del escenario (mismo gate que PUT celda/carryover/line: `get_current_user`, sin gate nuevo). INVARIANTE V1.1 (SD7-10): el PUT NO cambia de contrato ni de respuesta (fuente comercial del detail completo del escenario).
- **BR-IB-04 (GET, V1.1):** `GET /budget/planning/{id}/initial-balance`: responde config del escenario + resolucion de fuente, y LA FUENTE SE RESUELVE SIEMPRE (SD7-10), independientemente de los modos configurados, reutilizando `get_carryover_source_budget()` (candidatos del ano N-1 relativo al `budget_year` del escenario propio; prioridad ACTIVE > CLOSED > draft, `updated_at DESC`, `id_budget DESC`). Con candidato: `carryover_source` con `{id_budget, budget_name, budget_year, status}` y `unavailable_reason: null`, sea cual sea la combinacion de modos. Sin candidato en N-1: 200 con `carryover_source: null` y `unavailable_reason: "no_source"` — tambien con ambos modos en `manual` (NUNCA error HTTP). El valor numerico derivado NO se computa server-side (SA-1).
- **BR-IB-02 (creacion):** `POST /budget/planning/upload` acepta 4 campos multipart OPCIONALES: `initial_cash_mode`, `initial_cash_manual`, `initial_warehouse_mode`, `initial_warehouse_manual`. Aplicarlos al Budget creado. Si no llegan (o llegan vacios/omitidos): default `manual`/`0` => clientes y flujos existentes no cambian de comportamiento (regresion cero).
- **BR-IB-05 (dinamica, sin estado):** sin snapshot: el valor por arrastre se deriva en cada lectura FE usando el escenario fuente actual; si N-1 cambia, se refleja automaticamente al leer N.
- **BR-IB-06 (regresion):** defaults manual/0 => cualquier escenario previo a la feature se comporta exactamente como hoy (el acumulado de caja arranca en 0, bodega en 0). Ningun payload existente cambia de forma, salvo claves aditivas nuevas.
- **BR-IB-07 (ortogonalidad con arrastre):** esta feature NO altera `include_carryover` ni el endpoint `/carryover` ni sus lineas. Configurar saldo inicial no activa ni desactiva el arrastre de lineas, y viceversa. Coexisten sin interferencia.
- **BR-IB-08 (validaciones):** `manual_value` acepta negativos para efectivo (sobregiro presupuestario valido); para bodega exige `>= 0` => 422 indicando el campo violado. Valores numericos finitos (no NaN/Infinity => 422).

## 5. API (router planning existente, `app/api/budget/planning.py`)

### 5.1 `PUT /budget/planning/{id_budget}/initial-balance` (sin slash final, convencion BE-S6) -> 200 `PlanningDetail`

Body (`PlanningInitialBalanceSet`):

```json
{
  "cash":      { "mode": "manual",    "manual_value": 0.0 },
  "warehouse": { "mode": "carryover", "manual_value": 0.0 }
}
```

Validacion Pydantic: `mode` en `Literal["carryover","manual"]`; si `cash.mode` o `warehouse.mode` es invalido => 422; `warehouse.manual_value` >= 0 (BR-IB-08); el payload completo es obligatorio (los dos saldos siempre viajan juntos; faltante => 422).

### 5.2 `GET /budget/planning/{id_budget}/initial-balance` (sin slash final) -> 200 `PlanningInitialBalanceDetail`

```json
{
  "cash":      { "mode": "manual",    "manual_value": 0.0 },
  "warehouse": { "mode": "manual",    "manual_value": 0.0 },
  "carryover_source": { "id_budget": 576, "budget_name": "Presupuesto 2025", "budget_year": 2025, "status": "active" },
  "unavailable_reason": null
}
```

EJEMPLO V1.1 AMBOS MANUAL CON FUENTE (SD7-10): aunque los dos modos sean `manual`, la fuente N−1 se devuelve resuelta si existe (asi el FE puede ofertar "Continuar con el presupuesto meta del ano anterior" sin falso aviso). Y sin candidato en N−1 (cualquier combinacion de modos):

```json
{
  "cash":      { "mode": "carryover", "manual_value": 0.0 },
  "warehouse": { "mode": "manual",    "manual_value": 0.0 },
  "carryover_source": null,
  "unavailable_reason": "no_source"
}
```

(antes de la enmienda, con ambos manual y fuente existente, `carryover_source` venia `null` con `unavailable_reason: null` — ese era el defecto reportado en el escenario 126).

- 404 si el escenario no existe (validar pertenencia primero, patron del router). 404 literal `"Budget 999999 not found"`.
- `unavailable_reason` posibles: `null` | `"no_source"` (N−1 sin escenario meta, con cualquier combinacion de modos — v1.1). No agregar mas por ahora.
- El valor numerico derivado NO se computa server-side (SA-1): el FE se encarga con su motor y los datos de la fuente.

## 6. NFR

| ID | Requisito |
|---|---|
| NFR-IB-BE-1 | Costo (v1.1): la fila del presupuesto ya viene cargada por el flujo del endpoint; el GET paga SIEMPRE <= 2 queries totales (fila + la UNICA query SQL de fuente, filtrada/ordenada en SQL — sin N+1). PUT => 1 UPDATE. (En v1.0 el GET manual/manual pagaba 0 queries de fuente; desaparece por SD7-10.) |
| NFR-IB-BE-2 | Regresion: payloads existentes sin cambios de forma (claves aditivas); comprobable con AC. |
| NFR-IB-BE-3 | Convenciones: `db.query` legado; auth espejo del router planning (`get_current_user` de `app.core.auth`, `Exceptions` de `app.api.utils` si aplica); NO crear modulos nuevos (todo dentro de los archivos existentes del modulo). CamelCase solo si un archivo nuevo fuese imprescindible. |

## 7. Criterios de aceptacion (smoke BE)

- **AC-S7-BE-1:** `POST /upload` sin los 4 campos => presupuesto creado con `manual`/`0` en ambos saldos; con ellos => persistidos tal cual (incluye modo `carryover`).
- **AC-S7-BE-2:** PUT roundtrip: PUT con modos/valores => 200 y el detalle (y el GET) reflejan la configuracion; persistente (recarga identica).
- **AC-S7-BE-3:** PUT con `mode: "auto"` => 422; bodega con `manual_value: -100` => 422; efectivo con `-100` => 200 (permitido).
- **AC-S7-BE-4:** GET con un modo carryover sin fuente en N-1 => 200 con `unavailable_reason: "no_source"` (no error).
- **AC-S7-BE-5 (v1.1):** GET con ambos modos `manual` => 200 y `carryover_source` RESUELTA si existe en N−1 (con id/name/year/status — verificado contra el escenario 126: fuente = 576 active), `unavailable_reason: null`; sin fuente => `carryover_source: null` + `unavailable_reason: "no_source"` (v≤1.0 devolvia null/null — defecto corregido por SD7-10). Solo 1 query extra de fuente en cualquier combinacion de modos.
- **AC-S7-BE-5b:** GET sin escenario en N−1 con CUALQUIER config de modos => 200 + `unavailable_reason: "no_source"` (nunca error HTTP).
- **AC-S7-BE-6:** GET con fuente: `carryover_source` respeta la prioridad ACTIVE > CLOSED > draft (empate a `updated_at DESC`).
- **AC-S7-BE-7:** togglear `include_carryover` no altera la config de saldo inicial y viceversa (verificacion ida y vuelta de ambos GET/carryover).
- **AC-S7-BE-8:** GET/PUT 404 literal `"Budget 999999 not found"`; body invalido de esquema => 422.
- **AC-S7-BE-9:** BD recreada con `create_all` + ALTERs => app arranca; filas existentes con `manual`/`0`.

## 8. Decision Log (sesion 2026-10-22, suposiciones aprobadas por el stakeholder)

| ID | Decision | Origen (suposicion aprobada) |
|---|---|---|
| SD7-1 | Eleccion independiente por saldo (puede combinar arrastre y manual) | A1 |
| SD7-2 | "Presupuesto meta del ano anterior" = fuente del ano N-1, mismas reglas de prioridad de BE-S6 | A2 (reuso diseno SD6-3) |
| SD7-3 | Valor manual cubre/reemplaza el arrastre cuando el modo manual esta activo; se persiste siempre | A3 |
| SD7-4 | Config editable en cualquier momento desde el editor (PUT independiente del upload) | A4 |
| SD7-5 | Sin fuente => degradacion amable (200 + `unavailable_reason`; FE cae a manual avisando), no bloqueo | A5 |
| SD7-6 | Config persistida en backend (columnas en `budgets`), no solo FE | A6 |
| SD7-7 | Convive con el arrastre existente sin duplicar controles ni interferir (features ortogonales) | A7 |
| SD7-8 | NO toca las lineas generado por Excel ni su semantica: solo los saldos iniciales | A8 |
| SD7-9 | La derivacion del valor por arrastre la hace el FE (contrato: BE entrega solo fuente o null) | Diseno tecnico (las formulas de flujo/bodega viven en `cashFlowPivot`, single source of truth) |
| SD7-10 | La fuente N−1 se resuelve SIEMPRE en el GET (tambien con ambos modos `manual`), para que el FE pueda ofertar "Continuar con el presupuesto meta del ano anterior" sin falso aviso de bloqueo | Enmienda v1.1 — reporte UX del stakeholder sobre el presupuesto 126 (2026-10-22: ambos manual respondia null/null y el FE mostraba una advertencia falsa) |

## 9. Riesgos y PQs

- **R-S7-1:** dos motores (FE deriva arrastre; BE valida) podrian divergir => mitigado: backend NO computa el valor derivado (solo entrega la fuente); la formula vive solo en FE.
- **R-S7-2:** fuente en DRAFT es volatil (borrable via BE-S4D/02_14) => FE muestra status y warning (escalon FE).
- **R-S7-3:** ALTERs olvidados en deploy => checklist paso 1 y nota en `note.md` (patron R-S6-3).
- **PQ-1:** arrastre multi-ano / selector de ano fuente (ya estaba en BE-S6 PQ-2); **PQ-2:** snapshot anual del saldo de cierre al activar el target; **PQ-3:** arrastre desde saldo real del ledger de pagos.

## 10. Checklist de implementacion

1. ALTERs documentados + 4 columnas en modelo => smoke de arranque (`create_all` + ALTERs en BD de dev).
2. Schemas `PlanningInitialBalanceSide`, `PlanningInitialBalanceSet`, `PlanningInitialBalanceDetail` (+ espejo aditivo en detalle/listado si aplica) + registro explicito en `app/schemas/__init__.py`.
3. CRUD en `app/crud/budget/planning.py`: helpers set/get de config + reuso de `get_carryover_source_budget` para la fuente; registrar exportes en `app/crud/__init__.py` si el patron lo exige.
4. API: 2 endpoints en `app/api/budget/planning.py` + 4 campos opcionales en `POST /upload` (no hay router nuevo => sin tocar `main.py`).
5. Smoke AC-S7-BE-1..9.
6. Congelar contrato => FE-S7 (`frontend.03_22_Spec_frontend_budget_planning_initial_balance.md`).
