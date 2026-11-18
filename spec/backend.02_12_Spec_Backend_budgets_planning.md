# Spec Backend: Módulo de Planeación y Escenarios (`/budget/planning/`)

| Campo | Valor |
|---|---|
| **Documento** | Spec Backend — Budget Planning (escenarios, ingesta SIIGO, clon %, celda, meta activa) |
| **ID de feature** | `BE-S4-BUDGET-PLANNING` |
| **Versión** | 1.1 — incluye **Enmienda A-01** (BR-TGT-03 extendido a cash-flow + normalización de literales; stakeholder 2026-09-10) |
| **Fecha** | 2026-09-10 |
| **Módulo** | `budget` → sub-router nuevo `/budget/planning` (6 endpoints) + cambios Q0 en `budgetEngine` en **ambos pilares** (BR-TGT-03 + A-01). **Cero tablas nuevas, cero columnas nuevas.** |
| **Consumidor** | `crm_frontend/spec/frontend.03_03_Spec_frontend_budget_planning.md` (FE-S4-BUDGET-PLANNING) |
| **Origen** | HSpec "Planeación y Escenarios" (gerencia) + sesión interactiva spec-definer (2026-09-10). ASM-10 resuelto: **formatos SIIGO *Solicitud de Presupuesto* como único contrato de ingesta** — sin plantilla matricial ni despivote. |
| **Estado de supuestos** | ASM-1,2,3,6,7,8,9,11,12 aprobados tal cual; ASM-4,5,10 corregidos por validación en código (§2). Ver §12 Decision Log. |
| **Convenciones obligatorias** | `AGENTS.md`: camelCase en archivos, checklist de 4 puntos de registro, CRUD estilo `db.query(...)`, imports canónicos. |

---

## 1. Objetivo

1. Cargar la **meta financiera anual** (escenario *Base*) desde los dos archivos oficiales de solicitud presupuestal (**Ingresos** y **Gastos**), creando **un único `Budget`** en una sola transacción todo-o-nada.
2. Crear **escenarios alternativos** por clonación con un ajuste porcentual (`modifier_pct`) instantáneo sobre los montos proyectados.
3. Permitir **edición puntual de una celda** (una `budget_line`) sin re-subir el Excel completo.
4. Designar **una única Meta Activa por año** (base o escenario) que los Dashboards de varianza (`/budget/analytics`, `budgetEngine`) usarán como referencia de comparación.

**Fuera de alcance (§1.2 de la spec consolidada):** eliminar escenarios (solo se archivan al perder la meta), auditoría/histórico por celda, workflow de aprobación, motor de varianza nuevo, formato matricial de importación, plantilla descargable nueva, presupuesto multi-año en un mismo evento de carga.

## 2. Contexto verificado en el código actual (2026-09-10)

- **Modelos suficientes, sin migraciones.** `Base.metadata.create_all` no cambia.
  - `app/models/budget/budget.py` → `budgets`: `id_budget`, `budget_name`, `budget_year`, `budget_period`, `id_department`, `status` (server_default `'draft'`; dominio usado `draft/active/closed`), `is_scenario` (Boolean), `parent_budget_id` (self-FK), `created_at`, `updated_at`.
  - `app/models/budget/budgetLine.py` → `budget_lines`: `id_budget_line`, `id_budget`, `id_cost_center`, `line_type` (enum `income/expense`), `budget_date` (Date), `payment_date` (Date, NULL), `id_collection` (NULL), `projected_amount` (Float), `description`, `behavior_type` (enum `fixed/variable_sales/variable_receivables`), `variable_rate` (Float, NULL).
  - `app/models/budget/costCenter.py` → `cost_centers` (`cost_center_code` unique, `id_line`, `is_active`). Catálogo maestro pre-existente.
- **`budget_scenarios` (what-if JSON) NO interviene** en este módulo.
- **ETLs ya implementados** en `app/utils/templates/budgetTemplates.py`: `process_budget_plan_income()` (~L1367) y `process_budget_plan_expense()` (~L1420). **NO se modifican.** Leen con `skiprows=7` (encabezado real en fila 8), primera hoja.
- **Endpoints legados que consumen esos ETLs** (`app/api/budget/upload.py`): `POST /budget/upload/budget-plan-income` (~L313) y `POST /budget/upload/budget-plan-expense` (~L428). Su comportamiento externo **no cambia** (AC-REG-01).
- **`budgetEngine`** (`app/services/budgetEngine.py`): **dos** resoluciones Q0 gemelas, ambas con `status=='active' AND is_scenario.is_(False)` + literales "non-scenario": `get_pnl` (~L307-L335, D-3/BR-17) y `get_cash_flow` (~L847-L871, D-7/BR-31); ante varios candidatos toman el `id_budget` menor + warning. **Cambios requeridos al motor: BR-TGT-03 en AMBOS bloques + normalización de literales (Enmienda A-01, §6).**
- **Router agregador** `app/api/budget/__init__.py`: ya monta sub-routers con `budget.include_router(...)`. Aquí se monta `planning_router` con `prefix="/planning"`. **NO tocar** `app/api/__init__.py` ni `app/main.py` (el router `budget` ya está incluido en `main.py:70`).
- **Archivos de validación de formato** (existen en el repo): `crm_backend/test/data/Formato Solicitud Presupuesto Ingresos.xlsx` y `... Gastos.xlsx`.
- **Smoke tests**: la carpeta `crm_backend/test/` tiene `test_*_smoke.py`. Crear `test_budget_planning_smoke.py` (§9.4).

## 3. Modelo de datos (mapeo de conceptos de la HSpec)

| Concepto de Planeación | Materialización existente | Regla |
|---|---|---|
| **Escenario** | Una fila de `budgets` (`id_budget` = identificador). | *Base* (por upload): `is_scenario=False`, `parent_budget_id=NULL`. *Alternativo* (por clone): `is_scenario=True`, `parent_budget_id` = fuente **directa** (clon de clon permitido; no se conserva linaje transitivo — ASM-6). |
| **Celda de meta** | Una fila de `budget_lines`. | `budget_date` = fecha explícita del Excel (**sin transformación** — ASM-3; no hay `date_from/date_to`). 1 fila de Excel → 1 o N `budget_lines` por reglas de pago (BR-ING-05). |
| **Meta Activa del año** | `budgets.status='active'` sobre exactamente un `budget_year`. | Puede ser escenario o base (ASM-2). Invariante "1 activo/año" garantizada en `set-target` (BR-TGT-01), no en BD. |
| **Dimensiones** | `cost_centers`, `collections`, `line_payment_rules`. | Sin cambios. |

### 3.1 Ciclo de vida de `budgets.status`

```
 (nuevo) --upload--> draft ------------------------> active ---(otro set-target)--> closed
              clone --> draft (is_scenario=True)          ^ |
                                                          | v
                                             set-target (reactiva closed) ---+
```
- Todo escenario es **editable por celda** sin importar su estado (`draft/active/closed`); ASM-7 (last-write-wins, sin control de concurrencia).
- `closed` no es terminal: puede volver a `active` vía `set-target`.

## 4. Formatos de ingesta — contrato de columnas (verificado contra los 2 archivos reales)

Estructura **LARGA/tabular** en ambos (encabezado en fila 8 → `skiprows=7`, primera hoja). **No se construye plantilla nueva**: los formatos SIIGO oficiales son el contrato. `BudgetTemplates` **no se toca**; solo se reusa.

### 4.1 Ingresos (`Requisición de Facturacion`) → `process_budget_plan_income()`

| Columna Excel | Mapeo | Regla |
|---|---|---|
| `Centro de Costo` | `id_cost_center` | Celda `"000101 Facturacion Costa (Z1)"` → primer token = `cost_center_code` (comportamiento legado). |
| `Fecha de la Facturación (Proyectada)` | `budget_date` (y base de `payment_date`) | Fecha explícita por fila. |
| `Temporada` | `id_collection` vía `short_collection_name` | No bloqueante: desconocida → NULL (igual que hoy). |
| `Monto` | `projected_amount` | No numérico → 0.0 (igual que hoy). |
| `Observaciones Adicionales` | `description` | — |
| *(fijo)* | `line_type='income'`, `behavior_type='fixed'` | — |

**BR-ING-05 (heredado, obligatorio):** las `line_payment_rules` de la línea del CECO **dividen 1 fila de Excel en N `budget_lines`** con `payment_date` escalonada (`budget_date + payment_days`) y `projected_amount × payment_pct`, idéntico a `upload.py:366-398`. Una fila con regla única de 0 días → 1 línea. Las AC de "1 fila = 1 celda" cuentan **por fila de Excel**, no por línea generada.

### 4.2 Gastos (`Requisición de compra`) → `process_budget_plan_expense()`

| Columna Excel | Mapeo | Regla |
|---|---|---|
| `Centro de Costo` | `id_cost_center` | Primer token como código. |
| `Fecha del Gasto (Proyectada)` | `budget_date` | — |
| `Fecha de Pago (Proyectada)` | `payment_date` | — |
| `Concepto del Gasto` | `description` | — |
| `Temporada` | `id_collection` | Opcional (vacío en filas administrativas). |
| `Comportamiento` | `behavior_type` | `Fijo→fixed`, `Variable por Facturación→variable_sales`, `Variable por Recaudo→variable_receivables`. |
| `Monto o Tasa Solicitado` | `projected_amount` (fixed) **o** `variable_rate` (variable, con `projected_amount=0`) | Lógica condicionada legado (`budgetTemplates.py:1480-1485`). |

### 4.3 Validación de año (BR-ING-06, nueva)
Toda fila procesada debe cumplir `year(budget_date) == budget_year` del formulario. Si no: **400** `{"message":"Rows outside declared budget_year","found_years":[...]}` y rollback total. El formato permite mezclar años de proyección; este módulo agrupa por año.

## 5. API Backend — sub-router `/budget/planning/`

Archivo nuevo: `app/api/budget/planning.py` (nombre ya conforme a camelCase). Montado en `app/api/budget/__init__.py` con `prefix="/planning", tags=["Budget Planning"]`. **Todos** los endpoints exigen JWT (`from app.core.auth import get_current_user` → `Depends(get_current_user)`).

### 5.1 `POST /budget/planning/upload`
Crea el escenario (Base) y carga ambos archivos en **una sola transacción todo-o-nada**.

**Request `multipart/form-data`:**

| Campo | Tipo | Req | Default | Descripción |
|---|---|---|---|---|
| `scenario_name` | string ≤120 | Sí | — | Ej. "Plan Inicial 2027". |
| `budget_year` | int | Sí | — | 2000–2100 (422 fuera de rango). |
| `budget_period` | string ≤20 | No | `"ANUAL"` | — |
| `id_department` | int | No | NULL | — |
| `file_ingresos` | file `.xlsx` | **Sí** | — | §4.1. |
| `file_gastos` | file `.xlsx` | No | — | §4.2. Escenario sin gastos es válido. |

**Reglas de negocio:**
- **BR-ING-01** — Única transacción: `Budget` + líneas de ambos archivos. Cualquier fallo (CECO inexistente, año inconsistente, encabezado no reconocido) → **rollback total**: no queda ni escenario ni líneas. Patrón de rechazo del upload legado, extendido a 2 archivos.
- **BR-ING-02** — Escenario resultante: `is_scenario=False`, `status='draft'`, `parent_budget_id=NULL`, `budget_year` = declarado.
- **BR-ING-03** — CECO no resuelto → 400 `{"message":"Cost centers not found","missing_cost_centers":[...]}` (lista de códigos).
- **BR-ING-04** — Unicidad `(budget_year, budget_name)` → violación 400 `"Scenario name already exists for year <year>"` (aplica también a clone §5.2 y a este upload).
- **BR-ING-05** — Construcción de líneas **extraída a servicio compartido** (§7 T-02), reutilizada por el endpoint nuevo **y** por los dos legados (comportamiento externo idéntico).
- **BR-ING-06** — Validación de año (§4.3).

**Response 201** (JSON nuevo `PlanningUploadResult`):
```json
{ "id_budget": 42, "scenario_name": "Plan Inicial 2027", "budget_year": 2027,
  "lines_income": 128, "lines_expense": 96,
  "total_income": 320000000.0, "total_expense_fixed": 84000000.0,
  "payment_rules_expansions": 14 }
```
`total_expense_fixed` = Σ `projected_amount` de líneas expense (las variables aportan 0). `payment_rules_expansions` = líneas extra generadas por reglas de pago (= `lines_income − filas_de_excel_ingresos_procesadas`).

### 5.2 `POST /budget/planning/clone`
**Request JSON** (`PlanningCloneRequest`): `{ "id_budget": 42, "nuevo_nombre": "Plan 2027 +10%", "modifier_pct": 10.0 }` (`modifier_pct` opcional, default 0, **rango [-100, ∞)** → `< -100` da 422).

**Reglas:**
- **BR-CLN-01** — Copia lineal de **todas** las `budget_lines` del origen a un nuevo `Budget` (`is_scenario=True`, `parent_budget_id=id_budget`, `status='draft'`, `budget_year` = año del origen), en una transacción.
- **BR-CLN-02** — `projected_amount_nuevo = projected_amount × (1 + modifier_pct/100)`, float nativo, **sin redondeo**. `modifier_pct=0` → copia exacta.
- **BR-CLN-03** — `variable_rate` **se copia sin multiplicar** (es una tasa: escalar `0.08`→`0.088` corrompería el cash-flow del `budgetEngine`).
- **BR-CLN-04** — Clonar un clon o la Meta Activa: permitido. El origen se lee como snapshot y **nunca se muta**.
- **BR-CLN-05** — Origen inexistente → 404 (`Exceptions.register_not_found("Budget", id_budget)`); nombre duplicado en el año → 400 (BR-ING-04).

**Response 201:** objeto `Budget` del nuevo escenario (schema `Budget` ya registrado).

### 5.3 `PUT /budget/planning/cell/{id_budget_line}`
Edición puntual de **una** línea; no toca el resto del escenario.

**Request JSON** (`PlanningCellUpdate`): `{ "projected_amount": 5200000.0 }` (único campo requerido; `description: Optional[str]` opcional).

**Reglas:**
- **BR-CEL-01** — Solo muta `projected_amount` (`+ description` si viene). `budget_date`, `payment_date`, `line_type`, `behavior_type`, `variable_rate`, `id_cost_center`, `id_budget` son **inmutables** por esta vía.
- **BR-CEL-02** — Validación: numérico finito y `>= 0` (422 en otro caso; ASM-12).
- **BR-CEL-03** — Inexistente → 404. Sin bloqueo por estado y **last-write-wins** sin control de concurrencia (ASM-7).
- **BR-CEL-04** — Convivencia: el `PUT /budget/line/{id_budget_line}` legado (reemplazo total del objeto) **no se modifica**; este endpoint es el camino exclusivo del Grid Editor.

**Response 200:** `budget_line` actualizada (schema `BudgetLine`).

### 5.4 `GET /budget/planning/` (listado agregado del Dashboard)
Query `?budget_year=<int opcional>`. Devuelve escenarios **agregados en SQL** (NFR-5): por cada `budgets` → `budget_name`, `budget_year`, `is_scenario`, `parent_budget_name` (JOIN self por `parent_budget_id`), `status`, `lines_count`, `total_income` (Σ `projected_amount` where `line_type='income'`), `total_expense` (Σ where `'expense'`), `created_at`.
- Sin filtro de `is_scenario` (retorna base + alternativos). Sin paginación en MVP (decenas/año).
- Orden: `budget_year DESC`, luego `status` (`active` → `draft` → `closed`), luego `id_budget ASC`.
- **Response 200:** `[{ "id_budget":42, "budget_name":"Plan Inicial 2027", "budget_year":2027, "is_scenario":false, "parent_budget_name":null, "status":"active", "lines_count":224, "total_income":320000000.0, "total_expense":91200000.0, "created_at":"2026-09-10T14:22:00" }]`

### 5.5 `GET /budget/planning/{id_budget}/detail`
Wrapper del existente `GET /budget/full/{id_budget}` (`BudgetFull` = budget + `budget_lines`), **más** `parent_budget_name`. Fuente del Grid Editor; el pivote cc×mes se arma **en cliente** (sin endpoint matricial en backend, Opción 1). 404 si no existe.

### 5.6 `PUT /budget/planning/{id_budget}/set-target`
**Restringido a Gerencia/Sistema** (ASM-9): requiere `roles.role_name ∈ {Gerente, Administrador}` (nombres reales verificados en `crm_frontend/src/router/index.js:50-56`). Implementar como dependencia `require_target_admin` que resuelve el rol de `current_user` y devuelve **403** sin mutación si no aplica. `Financiero` puede subir/clonar/editar pero **NO** designar la meta (coherente con el gate visual de FE-S4 §3.3).

**Reglas:**
- **BR-TGT-01** — En una transacción: el escenario pasa a `status='active'` y **todo otro** `budgets` del **mismo** `budget_year` con `status='active'` pasa a `status='closed'`. Invariante: máximo un activo por año (garantizada aquí).
- **BR-TGT-02** — Idempotente: marcar el que ya es meta → 200 sin cambios.
- **BR-TGT-03 (v1.1)** — **Cambio en las DOS resoluciones Q0 de `budgetEngine`** (`get_pnl` ~L314 y `get_cash_flow` ~L854, Enmienda A-01 §6): reemplazar el predicado `status=='active' AND is_scenario.is_(False)` por `status=='active'` a secas (la Meta Activa puede ser escenario) y normalizar los literales de warning allí indicados. Con 0 activos por año → la semántica queda intacta (`budget=null` / salidas 0.0); solo cambia el texto del warning. Multi-activo es imposible por BR-TGT-01; si datos históricos lo tuvieran, mantener el `id_budget` menor + warning ya existente.

**Response 200:** `{ "id_budget":<n>, "budget_year":<año>, "demoted_budget_id":<anteror o null> }`

### 5.7 Matriz de códigos de error
| Situación | HTTP | Fuente |
|---|---|---|
| ID inexistente (cualquiera) | 404 | `Exceptions.register_not_found` |
| CECO desconocido / año inconsistente / nombre duplicado | 400 | `detail` estructurado |
| No-admin en `set-target` | 403 | `HTTPException` |
| `modifier_pct` o `projected_amount` inválidos / `budget_year` fuera de rango | 422 | validación Pydantic/`Query` |
| Token ausente/expirado | 401/403 | estándar `get_current_user` |

## 6. Cambios en `budgetEngine` (BR-TGT-03 · Enmienda A-01)

**Contexto (2026-09-10, aprobada por el stakeholder):** v1.0 limitó el cambio al Q0 de `get_pnl`, pero la HSpec original dice que "los Dashboards" (plural) miden la varianza contra la Meta Activa. Verificado en código: `get_cash_flow` (Pilar 2, D-7/BR-31, ~L847-L871) conservaba el predicado `is_scenario.is_(False)`; con Meta Activa-escenario, P&L compararía contra el escenario pero **liquidez advertiría "No active non-scenario budget" y compararía silenciosamente contra presupuesto vacío (0.0)**.

**Alcance v1.1:**
1. `get_pnl` Q0 (~L314-L322): predicado `is_scenario` removido — **ya implementado en v1.0**.
2. `get_cash_flow` Q0 (~L854-L859): remover `BudgetModel.is_scenario.is_(False)` de la consulta de candidatos, simétrico. Ninguna otra línea del método toca.
3. **Literales compartidos → normalizados** en ambos bloques:
   - `"No active non-scenario budget for {year}"` → `"No active budget for {year}"`
   - `"More than one active non-scenario budget for ..."` → `"More than one active budget for ..."`
   - `"Comparing against scenario budget"` **permanece** (literal espejo de 02_09/02_10, semántica inalterada).
   Coupling verificado por grep (2026-09-10): aserciones en `test_pnl_engine_smoke.py` (L827, L949), `test_cash_flow_engine_smoke.py` (constante L126) y `test_budget_planning_smoke.py` (L336, L793) — actualizarlas en la misma entrega. El frontend no referencia estos textos.
4. **Erratas documentales:** nota breve registrando el cambio de literal por A-01 en `backend.02_09` (AC-6) y `backend.02_10` (Q0 de §5, tabla de §6.1.2 y AC-12).
5. Verificación: AC-MT-2 (Pilar 1) + **AC-MT-4** (Pilar 2, nuevo) + **los tres smokes del motor corriendo completos** (guardia cruzada 02_09↔02_10↔02_12). Ningún otro cálculo (comisiones, buckets, clone-for-scenario, `project_cash_flow` legado) cambia.

## 7. Restricciones técnicas del repo

| ID | Restricción |
|---|---|
| **T-01** | Archivos nuevos camelCase: `app/api/budget/planning.py`, `app/crud/budget/planning.py`, `app/schemas/budget/planning.py`. Registros: schemas → **imports explícitos nombrados** en `app/schemas/budget/__init__.py` **y** re-export en `app/schemas/__init__.py` (seguir patrón actual de budget). CRUD → `from .planning import *` en su `__init__.py`. API sub-router → registrado **solo** en `app/api/budget/__init__.py`. **No tocar** `app/api/__init__.py` ni `app/main.py`. |
| **T-02** | **Refactor obligatorio:** extraer la construcción de line-records de los uploads legados a un servicio compartido (p. ej. `app/services/budgetPlanningIngestion.py` con `build_income_line_records(db, records, id_budget)` / `build_expense_line_records(db, records, id_budget)`), reutilizado por `POST /budget/planning/upload` **y** por `/budget/upload/budget-plan-income|expense` legados, cuyo comportamiento externo queda **idéntico** (AC-REG-01). **No duplicar** la lógica de `line_payment_rules`. |
| **T-03** | CRUD estilo legado `db.query(Model).filter(...)`; primera arg `db: Session`. Reusar `create_budget_lines_bulk`, `update_budget_line`, `get_cost_center_by_code`, `get_line_payment_rules_by_line`, `get_collection_by_short_name`, `get_budget_by_id`. |
| **T-04** | Imports canónicos: `from app import get_db`, `from app.core.auth import get_current_user`, `import app.crud as crud`, `from app.api.utils import Exceptions`, `from app.schemas import ...`. |
| **T-05** | Transaccionalidad: commit único al final de cada operación de escritura; `db.rollback()` en `except`. Upload/clone/set-target atómicos. |
| **T-06** | Precisión monetaria: persistir en `Float` (columnas existentes). Multiplicación de clone sin `round()`. En cell update, validar `>=0` y finito. |

## 8. Requisitos No Funcionales (backend)
| # | Requisito | Valor medible |
|---|---|---|
| NFR-1 | Upload 500 filas/archivo (≤10 MB) | **< 5 s p95** |
| NFR-2 | `PUT /cell` y `set-target` | **< 300 ms p95** |
| NFR-3 | Integridad | upload/clone/set-target atómicos (rollback completo), probado por AC |
| NFR-4 | Seguridad | JWT en los 6 endpoints; 403 en set-target sin rol admin; ningún endpoint anónimo |
| NFR-5 | Escalamiento | ≥20 escenarios/año ×1200 líneas sin degradar el listado (§5.4 agregación en SQL) |
| NFR-6 | Compatibilidad | Cero tablas nuevas, cero migraciones; el sistema opera igual si nadie usa el módulo (AC-REG) |

## 9. Criterios de Aceptación (backend)

**Upload**
- **AC-UP-1** — Par de archivos de `crm_backend/test/data/` con `budget_year=2027` → 201; 1 `Budget` (`draft`, `is_scenario=False`) + ingresos (con expansiones de `line_payment_rules` idénticas al legado para los mismos archivos) + gastos (tipos `fixed/variable_sales/variable_receivables` correctos; en variables `projected_amount=0` y `variable_rate`=tasa del Excel).
- **AC-UP-2** — Un CECO inexistente en el archivo de gastos → 400 con lista y **cero registros** en BD (incluye rollback del `Budget`).
- **AC-UP-3** — Archivo con filas en 2026 y `budget_year=2027` declarado → 400 `found_years` + cero registros.
- **AC-UP-4** — Repetir `scenario_name` en el mismo año → 400.

**Clone**
- **AC-CL-1** — `modifier_pct=10` sobre escenario de 224 líneas → nuevo escenario con 224 líneas, `Σ projected_amount` = 1.10 × Σ origen (tolerancia float 1e-6), `parent_budget_id` e `is_scenario=True` correctos, `status='draft'`.
- **AC-CL-2** — Línea con `variable_rate=0.08` → el clon conserva **0.08** (no 0.088).
- **AC-CL-3** — `modifier_pct=-100` → todo `projected_amount=0`; `-101` → 422.

**Celda**
- **AC-CE-1** — `PUT /cell/{id}` con monto válido → 200; solo cambian `projected_amount` e `updated_at`; las demás líneas quedan byte-idénticas.
- **AC-CE-2** — `-5` → 422; id inexistente → 404.
- **AC-CE-3** — Dos escrituras concurrentes → gana la última, ambas 200 (sin bloqueo).

**Meta Activa**
- **AC-MT-1** — Con base B2027 `active`, `set-target` escenario A → A=`active`, B=`closed`; un tercer intento con C deja A=`closed`. `GET /budget/planning/?budget_year=2027` → un único `status='active'`.
- **AC-MT-2** — Tras AC-MT-1, `GET /budget/analytics/pnl` (Pilar 1) **sin** `id_budget` compara contra **A** (escenario), no contra B. El equivalente de liquidez se acepta por **AC-MT-4** (A-01).
- **AC-MT-3** — Usuario no-admin → 403 y sin mutación.
- **AC-MT-4 (A-01)** — Con la Meta Activa = escenario A, `GET /budget/analytics/cash-flow` **sin** `id_budget` resuelve A: `meta.budget_source.id_budget == A`, **sin** warning `"No active budget for {año}"`, y las salidas de presupuesto (Q5) provienen de A. Con `id_budget` explícito el comportamiento no cambia.

**Regresión (obligatoria antes de merge)**
- **AC-REG-01** — `/budget/upload/budget-plan-income|expense` y `/budget/analytics/clone-for-scenario` producen resultados **idénticos** a los actuales con los archivos de `test/data/` (el refactor T-02 no cambia comportamiento).
- **AC-REG-02 (v1.1)** — Con 0 presupuestos `active` en el año, pnl y cash-flow responden con la **misma semántica** que hoy (`budget=null` / salidas 0.0 / tie-break menor id); la ÚNICA diferencia válida es el texto del warning normalizado por A-01 ("No active budget for {año}").

### 9.4 Smoke test
Crear `crm_backend/test/test_budget_planning_smoke.py` siguiendo el patrón de `test_actual_cost_smoke.py`: cubre AC-UP-1..4, AC-CL-1..3, AC-CE-1..3, **AC-MT-1..4**, AC-REG-01..02 contra los 2 archivos de `test/data/` en un schema aislado, y **debe ejecutarse y pasar**. Con A-01 la entrega corre además `test_pnl_engine_smoke.py` y `test_cash_flow_engine_smoke.py` completos (guardia cruzada: los tres pilares comparten `budgetEngine.py`), con sus aserciones de literal actualizadas.

## 10. Archivos a crear / modificar
| Acción | Ruta | Claves |
|---|---|---|
| Crear | `app/api/budget/planning.py` | 6 endpoints, JWT, admin en set-target |
| Crear | `app/schemas/budget/planning.py` | `PlanningCloneRequest`, `PlanningCellUpdate`, `PlanningUploadResult` (y row schema §5.4) |
| Crear | `app/crud/budget/planning.py` | `get_planning_scenarios`, `clone_budget_with_modifier`, `update_budget_line_cell`, `set_active_target`, `budget_year_active_exists`, `get_budget_with_parent_name` |
| Crear | `app/services/budgetPlanningIngestion.py` | `build_income_line_records`, `build_expense_line_records` (T-02) |
| Modificar | `app/api/budget/__init__.py` | `include_router(planning_router, prefix="/planning", tags=["Budget Planning"])` |
| Modificar | `app/schemas/budget/__init__.py` + `app/schemas/__init__.py` | imports explícitos nombrados |
| Modificar | `app/crud/budget/__init__.py` | `from .planning import *` |
| Modificar | `app/api/budget/upload.py` | delegar a servicio T-02 (comportamiento idéntico) |
| Modificar | `app/services/budgetEngine.py` | Q0 en `get_pnl` **y** `get_cash_flow`: fuera el predicado `is_scenario` + literales normalizados (BR-TGT-03 + A-01) — **nada más** |
| Modificar | `test/test_pnl_engine_smoke.py` · `test/test_cash_flow_engine_smoke.py` · `test/test_budget_planning_smoke.py` | A-01: actualizar aserciones del literal de warning y **correr los tres** |
| Modificar | `spec/backend.02_09_Spec_Backend_budgets_pnl_engine.md` (AC-6) · `spec/backend.02_10_Spec_Backend_budgets_cash_flow_engine.md` (Q0 §5, §6.1.2, AC-12) | Nota de errata: el literal del warning cambió por A-01 (esta spec §6) |
| Crear | `test/test_budget_planning_smoke.py` | §9.4 |

## 11. Preguntas abiertas para el equipo (no bloquean el MVP)
- **PQ-1 (resuelto, registrar al implementar)** — Roles reales en el CRM: `Gerente`, `Financiero`, `Administrador`. `set-target` exige `Gerente` o `Administrador` vía `require_target_admin`; verificar contra el seed de `roles` en BD; semántica de los demás endpoints intacta (JWT estándar, sin gate de módulo — asumiendo decisión ASM-9 para upload/clone/cell: cualquier autenticado del CRM).
- **PQ-2** — `budget_period` default `"ANUAL"`: confirmar que la cadena ≤20 no colisiona con valores usados en analytics (hoy es string libre).

## 12. Decision Log
| ID | Decisión | Origen |
|---|---|---|
| ASM-1 | Escenario = fila de `budgets`; `scenario_id` = `id_budget`; no se crea tabla nueva. | Aprobado tal cual |
| ASM-2 | `is_active_target` = `status='active'`; la meta puede ser escenario → cambio Q0 (BR-TGT-03). | Aprobado |
| ASM-3 | Sin `date_from/date_to` en la celda; `budget_date` = fecha explícita del Excel; el rango mes es derivado en cliente. | Aprobado |
| ASM-6 | Clon plano re-clonable; `parent_budget_id` a fuente directa; linaje no transitivo. | Aprobado |
| ASM-7 | `PUT /cell` sin auditoría ni control de concurrencia (last-write-wins). | Aprobado |
| ASM-8 | Meta activa exclusiva por año; el anterior pasa a `closed`. | Aprobado |
| ASM-9 | JWT para todos; **admin** para set-target. | Aprobado (PQ-1) |
| ASM-11 | Eliminar escenarios fuera de MVP (solo se archiva al perder la meta). | Aprobado |
| ASM-12 | Grid solo numéricos `>=0`; sin fórmulas/rangos. | Aprobado |
| **ASM-4 (corregido)** | La ingesta produce **ambos** tipos de línea (ingresos + gastos) vía **dos archivos**, no solo ingresos. | Validación en código (Opción 1) |
| **ASM-5 (corregido)** | CECOs por **primer token** de la celda "código+nombre"; rechazo total si desconocidos. | Validación en código |
| **ASM-10 (corregido)** | **Sin plantilla matricial nueva**: los 2 formatos SIIGO *Solicitud* son el contrato; no hay despivote. | Rechazado por stakeholder → Opción 1 (2026-09-10) |
| **A-01 (v1.1)** | BR-TGT-03 extendido a `get_cash_flow` + literales de warning normalizados; nace AC-MT-4; AC-REG-02 redefinida (semántica igual, texto distinto); erratas en 02_09/02_10. | Stakeholder "Extiéndelo" (2026-09-10), tras hallazgo en la verificación post-implementación |

## 13. Trazabilidad (HSpec → esta spec)
| HSpec | Sección |
|---|---|
| §2 `scenario_id` / agrupación | §3 (ASM-1) |
| §2 `is_active_target` ("los Dashboards", plural) | §3 + §5.6 + §6 (ASM-2, BR-TGT-03; **A-01 cubre el Pilar 2**, AC-MT-4) |
| §3.2 Excel matricial + §4.1 unpivot | **REEMPLAZADO** por §4 (SIIGO largos, sin despivote) |
| §4.1 `POST /upload` | §5.1 |
| §4.2 `POST /clone` + `modifier_pct` | §5.2 (tasas excluidas de escala, BR-CLN-03) |
| §4.3 `PUT /cell/{id_budget_line}` | §5.3 |
| Dashboards usan meta activa | §6 (cambio Q0), AC-MT-2 |