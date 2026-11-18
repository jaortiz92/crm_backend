# Spec Backend: CRUD de Líneas de Escenario (`/budget/planning/…/line`)

| Campo | Valor |
|---|---|
| **Documento** | Spec Backend — creación / edición de campos / eliminación de `budget_lines` de escenarios (complemento de BE-S4) |
| **ID de feature** | `BE-S4D-BUDGET-LINES` |
| **Versión** | 1.0 |
| **Fecha** | 2026-09-11 |
| **Módulo** | `budget` — 3 endpoints NUEVOS en el sub-router existente `/budget/planning` (`app/api/budget/planning.py`). **Cero tablas nuevas, cero columnas nuevas, cero archivos de modelo nuevos.** |
| **Base** | `backend.02_12` (BE-S4-BUDGET-PLANNING) §5.3: hoy SOLO existe `PUT /cell` (BR-CEL-01: únicamente `projected_amount` + `description`). Este documento RELAJA BR-CEL-01 vía endpoints nuevos SIN modificar `PUT /cell`. |
| **Consumidor** | `crm_frontend/spec/frontend.03_06_Spec_frontend_budget_planning_line_manager.md` (FE-S4D-BUDGET-LINES) |
| **Origen** | Historia "el Editor de Celdas debe PERMITIR MODIFICAR (crear/editar/campos/eliminar); ingresos más manejables si se muestran separados" + sesión spec-definer 2026-09-11 (Opción A del stakeholder; supuestos funcionales 1–8 aprobados). |
| **Estado de supuestos** | Aprobados tal cual: 1–8 de la sesión. Decisiones D-1…D-9 en §9. |
| **Convenciones obligatorias** | `AGENTS.md`: camelCase, imports canónicos, CRUD `db.query(...)` legado, registro explícito de schemas (no `*`), cero Alembic. |

---

## 1. Objetivo

Permitir la **gestión completa de líneas** de un presupuesto/escenario desde el editor, sin re-ingestar el Excel por cada corrección:

1. **Crear** una línea (ingreso o gasto; fija o variable).
2. **Editar** los campos estructurales de una línea existente (CECO, fechas, temporada, monto/tasa, descripción).
3. **Eliminar** una línea (borrado físico).

`PUT /budget/planning/cell/{id}` (edición rápida de monto por doble clic) **sigue vigente e inmutable** para no romper FE-S4/FE-S4B/FE-S4C (AC-FE-4, NFR-F2).

## 2. Contexto verificado en el código actual (2026-09-11)

| Hecho | Fuente |
|---|---|
| `PUT /cell` muta SOLO `projected_amount` (+`description` opcional); el resto de campos es inmutable y `variable_rate` NO se toca | `crud/budget/planning.py::update_budget_line_cell` (BR-CEL-01) |
| Sin lock por `status`: líneas de presupuestos draft/active/closed son editables, last-write-wins | BR-CEL-03 / ASM-7 (mismo docstring) |
| `BudgetLine` modelo: `id_budget, id_cost_center, line_type(enum income/expense), budget_date(NOT NULL), payment_date(NULL), id_collection(NULL), projected_amount(NOT NULL default 0), description(NULL), behavior_type(enum fixed/variable_sales/variable_receivables, default fixed), variable_rate(NULL)` | `app/models/budget/budgetLine.py` |
| `BudgetLineBase` YA valida: `projected_amount ge=0`; `variable_rate 0–1` y OBLIGATORIA si `behavior_type != fixed` (field_validator) | `app/schemas/budget/budgetLine.py` |
| Ingesta fuerza `projected_amount = 0` en líneas variables (AC-UP-1); monto variable es DERIVADO (BR-CLN-03) | `budgetPlanningIngestion.py` / FE-S4C §4.4 |
| `budget_lines` no tiene FK entrante de otras tablas → borrarlo no encadena nada | `app/models/budget/*.py` (sin referencias) |
| El listado (`GET /budget/planning/`) y el detalle recalculan Σ en SQL en cada fetch → el FE puede mutar su caché local y pedir refresco suave | `crud/budget/planning.py::get_planning_scenarios` |

## 3. API — 3 endpoints nuevos en el router `/budget/planning`

Dependencia de seguridad idéntica al resto del módulo: `current_user: User = Depends(get_current_user)` (JWT). SIN gate de rol adicional (misma política de upload/clone/cell: D-7); el gate de roles es de menú (FE) y `set-target` no cambia.

### 3.1 `POST /budget/planning/{id_budget}/line` → 201 `BudgetLine`

Body `PlanningLineCreate` (nuevo schema en `app/schemas/budget/planning.py`; reutiliza los enums/validadores de `budgetLine.py`):

```python
class PlanningLineCreate(BaseModel):
    id_cost_center: int = Field(..., gt=0)
    line_type: LineTypeEnum                      # requerido: lo fija la sección del editor
    budget_date: date
    payment_date: Optional[date] = None          # None ⇒ el servidor la deja NULL (fallback de lectura = budget_date, como hoy)
    id_collection: Optional[int] = Field(None, gt=0)
    projected_amount: float = Field(0, ge=0)     # ignorado-fuerza 0 si behavior != fixed (BR-LINE-03)
    description: Optional[str] = None
    behavior_type: BehaviorTypeEnum = BehaviorTypeEnum.FIXED
    variable_rate: Optional[float] = Field(None, ge=0, le=1)  # obligatoria si behavior != fixed (validador heredado del patrón BudgetLineBase, replicar)
```

Reglas:
- **BR-LINE-01**: `id_budget` debe existir y pertenecer al módulo presupuesto ⇒ si no, **404**.
- **BR-LINE-02**: FKs verificadas: `id_cost_center` inexistente ⇒ **404** con detalle `Cost center {id} not found`; `id_collection` no-null inexistente ⇒ **404** análogo. (No re-usar los códigos de `missing_cost_centers` de ingesta: esto es mutación unitaria, 404 basta.)
- **BR-LINE-03**: línea variable (`behavior_type != fixed`) ⇒ el servidor **fuerza `projected_amount = 0`** aunque el body traiga otro valor (invariante AC-UP-1/BR-CLN-03: el monto se deriva de la tasa; el FE ni lo envía). Si `behavior_type != fixed` y `variable_rate` null ⇒ **422** (validador).
- **BR-LINE-04**: `year(budget_date) == budgets.budget_year` ⇒ si no, **400** `"budget_date year {y} does not match scenario year {ay}"`. `payment_date` **sin** restricción de año (un pago a enero+1 del año siguiente es lícito — reglas de recaudo; Vista Flujo lo ubica por su mes).
- **BR-LINE-05**: cualquier `status` del presupuesto (draft/active/closed) es editable, last-write-wins (extensión explícita de BR-CEL-03; decisión D-5).
- Validación de formato/`ge=0`/`0–1`: pydantic ⇒ **422**.
- No se valida unicidad (mismo CECO+fecha+tipo puede repetirse: la ingesta ya genera múltiples líneas por par CECO/mes vía reglas de pago — decisión consciente D-4; la sección de ingresos las mostrará como filas hermanas).

### 3.2 `PUT /budget/planning/line/{id_budget_line}` → 200 `BudgetLine`

Body `PlanningLineUpdate`: TODOS los campos opcionales (`id_cost_center`, `budget_date`, `payment_date`, `id_collection`, `projected_amount`, `description`, `variable_rate`); omitted = keep (mismo contrato parcial que `LineCostRateUpdate`).

Reglas:
- **BR-LINE-06**: `line_type` y `behavior_type` **NO son editables** — no existen en el schema; si el cliente los envía, pydantic los ignora (default `extra='ignore'`). Cambiar de tipo/comportamiento = crear línea nueva + eliminar la vieja (D-2).
- **BR-LINE-07**: sobre línea **variable**: `projected_amount` presente ⇒ **400** `"variable lines derive their amount from the rate; edit variable_rate instead"`. `variable_rate` presente ⇒ valida `0–1` y se guarda. Sobre línea **fixed**: `variable_rate` presente ⇒ **400** análogo (una fixed no lleva tasa; D-3).
- **BR-LINE-08**: `budget_date` nuevo: mismo check BR-LINE-04 contra el año del presupuesto padre (join).
- 404 si la línea no existe; FKs como BR-LINE-02. Sin lock por status (BR-LINE-05).

### 3.3 `DELETE /budget/planning/line/{id_budget_line}` → 200 `{"deleted_id": int}`

- **Borrado físico** (`db.delete` + commit; D-2: sin flag blando ni papelera en v1).
- 404 si no existe. Sin cascadas (sin FK entrantes, §2). Sin lock por status.

### 3.4 Matriz de errores (todos los endpoints)

| Condición | Código | `detail` |
|---|---|---|
| Sin JWT / expirado | 401 | estándar FastAPI |
| `id_budget`/`id_budget_line`/FK inexistente | 404 | `"Budget {id} not found"` / `"BudgetLine {id} not found"` / `"Cost center {id} not found"` / `"Collection {id} not found"` |
| Año `budget_date` ≠ año del escenario (BR-LINE-04/08) | 400 | ver §3.1 |
| Monto en variable / tasa en fixed (BR-LINE-07) | 400 | ver §3.2 |
| Schema (negativos, tasa fuera de 0–1, variable sin tasa, no numérico) | 422 | pydantic |

## 4. Capa CRUD (`app/crud/budget/planning.py`, estilo `db.query`)

```python
def create_planning_line(db: Session, id_budget: int, payload: PlanningLineCreate) -> BudgetLine
def update_planning_line(db: Session, id_budget_line: int, payload: PlanningLineUpdate) -> Optional[BudgetLine]  # None ⇒ 404 en API
def delete_planning_line(db: Session, id_budget_line: int) -> Optional[BudgetLine]
```

- Verificaciones (presupuesto, FKs, año del budget_date, comportamiento↔campos) dentro del CRUD, lanzando `fastapi.HTTPException` como hacen `lineCostRate.py`/`update_budget_line_cell` — no `Exceptions.register_not_found` para los 400 propios (mantener el patrón exacto de cada caso ya usado en el repo).
- Sin `flush()` parcial: un solo `commit` por operación (idempotencia de sesión legacy del repo).

## 5. Puntos de registro (checklist AGENTS.md, versión reducida — sin modelo/archivo nuevos)

1. `app/schemas/budget/planning.py`: `PlanningLineCreate`, `PlanningLineUpdate` → registrar en `app/schemas/budget/__init__.py` **y** `app/schemas/__init__.py` (import nombrado explícito, NO `*`).
2. `app/crud/budget/planning.py`: funciones §4 (el `crud/budget/__init__.py` ya exporta `planning.py`; verificar estilo de re-export actual).
3. `app/api/budget/planning.py`: 3 endpoints §3 en el router existente → ya registrado en `app/api/__init__.py` y `app/main.py` (no tocar).
4. CERO modelos, CERO tablas, CERO columnas, CERO Alembic.

## 6. Requisitos no funcionales

| ID | Requisito |
|---|---|
| NFR-L-1 | Latencia < 150 ms p50 (mutación unitaria + 3–4 SELECT de verificación con índice en FK/PK). |
| NFR-L-2 | Respuestas = el objeto `BudgetLine` completo para que el FE actualice su caché sin refetch (contrato AC-FD-x del consumidor). |
| NFR-L-3 | OpenAPI: los 3 endpoints documentados con `response_model=BudgetLine` (o el dict del DELETE) — verificable sin auth (`/openapi.json`). |
| NFR-L-4 | Las vistas derivadas (P&L, cash-flow, listados) no cambian de contrato: siguen leyendo `budget_lines`. |
| NFR-L-5 | `PUT /cell` y `POST /clone`/`/upload` SIN alteración conductual (regresión AC-UP/AC-CL/AC-CE del smoke de 02_12 debe seguir en verde). |

## 7. Criterios de aceptación (smoke: `test/test_budget_planning_lines_smoke.py`)

* **AC-LINE-1:** POST fixed-income válido sobre escenario draft ⇒ 201, `id_budget_line` > 0, `GET …/detail` la incluye, Σ `total_income` del listado sube en exactamente el monto.
* **AC-LINE-2:** POST `behavior_type=variable_sales` ⇒ 201 con `projected_amount = 0` aunque el body pidiera 500000 (BR-LINE-03); sin `variable_rate` ⇒ 422.
* **AC-LINE-3:** POST con `budget_date` de año distinto al del escenario ⇒ 400 con detalle exacto (BR-LINE-04); con `payment_date` en enero del año siguiente ⇒ 201 (sin check de año en pago).
* **AC-LINE-4:** POST `id_cost_center=999999` inexistente ⇒ 404.
* **AC-LINE-5:** PUT que cambia CECO+fechas+temporada+descripción sobre línea fixed ⇒ 200 con los campos nuevos persistidos (leídos por detail fresh, no de la respuesta).
* **AC-LINE-6:** PUT `projected_amount` sobre línea variable ⇒ 400 (BR-LINE-07); PUT `variable_rate=0.08` sobre la misma ⇒ 200 y el P&L de analítica (get_pnl del periodo que la cubre) refleja la nueva tasa.
* **AC-LINE-7:** PUT con `line_type`/`behavior_type` en el body ⇒ 200 y ambos campos INVARIANTES (BR-LINE-06).
* **AC-LINE-8:** PUT/DELETE sobre `id_budget_line=999999` ⇒ 404; DELETE exitoso ⇒ 200 y la línea desaparece de `detail` y de los pivotes (Σ del listado baja exactamente el monto); DELETE sobre escenario `closed` ⇒ 200 (BR-LINE-05).
* **AC-LINE-9:** PUT `projected_amount=-1` ⇒ 422; PUT `variable_rate=19` (confundido con %) ⇒ 422 (le=1) — el FE convierte.
* **AC-LINE-10:** JWT ausente ⇒ 401 en los 3 endpoints; `GET /openapi.json` sin auth muestra los 3 con schemas registrados.
* **AC-LINE-11:** Regresión 02_12: `python test/test_budget_planning_smoke.py` + pnl + cash-flow smoke ⇒ verdes sin tocar ninguno de sus archivos (NFR-L-5).
* **AC-LINE-12:** Cero DDL: `to_regclass` de las tablas fuente sigue en 0 cambios; ninguna migración/Alembic nueva en el diff.

## 8. Archivos a crear / modificar

| Archivo | Acción |
|---|---|
| `app/schemas/budget/planning.py` | MODIFICAR: + `PlanningLineCreate`, + `PlanningLineUpdate` |
| `app/schemas/budget/__init__.py` y `app/schemas/__init__.py` | MODIFICAR: exports nombrados |
| `app/crud/budget/planning.py` | MODIFICAR: 3 funciones §4 |
| `app/api/budget/planning.py` | MODIFICAR: 3 endpoints §3 (tras `planning_update_cell`) |
| `test/test_budget_planning_lines_smoke.py` | **NUEVO** (patrón de los smokes existentes de planning) |
| `app/main.py`, `app/api/__init__.py`, `app/models/*`, `app/db.py` | **INTOCADOS** |

## 9. Decision Log (sesión spec-definer 2026-09-11 — supuestos aprobados)

| ID | Decisión | Origen |
|---|---|---|
| D-1 | Opción A (evolver el tab existente en backend = CRUD de líneas; sin ruta nueva ni matriz editable) | Stakeholder eligió opción recomendada |
| D-2 | DELETE es físico, sin deshacer/papelera v1 | Supuesto 2 aprobado |
| D-3 | `line_type`/`behavior_type` inmutables ⇒ crear+eliminar (BR-LINE-06/07) | Supuesto 3 aprobado |
| D-4 | Sin restricción de unicidad (CECO+fecha+tipo repetibles, como la ingesta multi-línea por reglas de pago) | Supuesto 6 aprobado + verificación §2 |
| D-5 | Editable en cualquier status, last-write-wins (misma BR-CEL-03 que hoy tiene el monto) | Supuesto 5 aprobado |
| D-6 | Invariantes de variable: monto 0 forzado, tasa 0–1 obligatoria, PUT rechaza monto | Supuesto 4/§2 AC-UP-1 |
| D-7 | Sin gate de rol nuevo (JWT como upload/clone/cell); roles = menú FE | Patrón BE-S4 vigente |
| D-8 | `PUT /cell` intocado; coexistencia de ambos caminos de edición | Regresión AC-FE-4 |
| D-9 | Sin historial/auditoría de mutaciones (ASM-7 sigue vigente: el UI muestra estados de guardado, no quién editó) | Supuesto/ASM-7 02_12 |

## 10. Riesgos

* **R-1 (bajo):** sin deshacer, un DELETE masivo por confusión del usuario solo se repara re-ingestando o clonando. Mitigación FE: confirmación destructiva con datos de la fila (spec consumidora §4.3).
* **R-2 (aceptado):** `payment_date` fuera del año desplaza meses en Vista Flujo (FE-S4B) — semántica correcta (el efectivo cae cuando cae), documentada aquí.
* **R-3 (bajo):** crear líneas con CECO de otro dominio (p. ej. gasto-only) no se impide: un ingreso con CECO de gasto es lícito contablemente y la ingesta no lo distingue; el usuario responde. PQ-BD-1.

## 11. Preguntas abiertas (no bloquean)

* **PQ-BD-1:** ¿Soft-delete (`is_deleted`) + "deshacer" en toast v2?
* **PQ-BD-2:** ¿Endpoint PATCH que cambie `behavior_type` (fixed⇄variable) con migración de monto→tasa?
* **PQ-BD-3:** ¿Bulk create (pegar TSV de celdas) — lo pide el patrón Excel de los usuarios?

## 12. Trazabilidad

| Concepto de la historia | Sección |
|---|---|
| "permita modificar" (crear/editar/eliminar) | §3.1–3.3 |
| Variables corregibles sin re-ingesta (supuesto 4) | §3.2 BR-LINE-07 |
| Sin cambios de tipo/comportamiento (supuesto 3) | BR-LINE-06 |
| Estados no bloquean (supuesto 5) | BR-LINE-05 |
| Coherencia inmediata de vistas (supuesto 8) | NFR-L-2 (respuesta completa → caché FE) |