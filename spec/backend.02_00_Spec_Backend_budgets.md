# Especificación Técnica Implementada: Módulo de Presupuesto y Flujo de Caja

## 1. Arquitectura y Estándares (*Architecture & Standards*)

*   **Enfoque Arquitectónico:** Modular Monolith dentro del ecosistema FastAPI, aislado bajo el enrutador `/budget/`.
*   **Estructura Modular:** Cada capa (models, schemas, crud, api) tiene una carpeta `budget/` con archivos individuales por entidad en camelCase.
*   **Convenciones de Código:**
    *   SQLAlchemy sincrónico (`psycopg2`) con estilo CRUD legado (`db.query(Model).filter(...)`).
    *   Checklist de 4 pasos completado: `models` → `schemas` → `crud` → `api`.
*   **Seguridad:** Todos los endpoints protegidos con `get_current_user` (JWT auth).

### Estructura de Archivos Creada

```
crm_backend/app/
├── models/budget/                    (9 archivos)
│   ├── __init__.py                   ← Re-exporta las 8 entidades
│   ├── costCenter.py
│   ├── actualExpense.py
│   ├── actualCost.py
│   ├── budget.py
│   ├── budgetLine.py
│   ├── accountReceivable.py
│   ├── paymentLedger.py
│   └── budgetScenario.py
├── schemas/budget/                   (9 archivos)
│   ├── __init__.py                   ← Re-exporta todos los schemas
│   ├── costCenter.py
│   ├── actualExpense.py
│   ├── actualCost.py
│   ├── budget.py                     ← Incluye schemas analíticos
│   ├── budgetLine.py
│   ├── accountReceivable.py
│   ├── paymentLedger.py
│   └── budgetScenario.py
├── crud/budget/                      (9 archivos)
│   ├── __init__.py                   ← from .modulo import * (8 módulos)
│   ├── costCenter.py
│   ├── actualExpense.py
│   ├── actualCost.py
│   ├── budget.py
│   ├── budgetLine.py
│   ├── accountReceivable.py
│   ├── paymentLedger.py
│   └── budgetScenario.py
├── api/budget/                       (11 archivos)
│   ├── __init__.py                   ← Router principal que agrega sub-routers
│   ├── costCenter.py
│   ├── actualExpense.py
│   ├── actualCost.py
│   ├── budget.py
│   ├── budgetLine.py
│   ├── accountReceivable.py
│   ├── paymentLedger.py
│   ├── budgetScenario.py
│   ├── upload.py                     ← Endpoints ETL
│   └── analytics.py                  ← Endpoints analíticos
├── utils/templates/
│   └── budgetTemplates.py            ← ETL para archivos Excel
└── services/
    ├── __init__.py
    └── budgetEngine.py               ← Motor financiero
```

---

## 2. Modelado de Base de Datos (*Database Modeling*)

### Grafo de Relaciones FK

```
Zone (1) ──── (N) Department (geográfico)
   │
   └── (N) CostCenter ──── Area (N) ──── (1) Management
              │
              └── Line (se mantiene)

cost_centers:
   ├── id_zone → zones.id_zone
   ├── id_area → areas.id_area
   └── id_line → lines.id_line

departments:
   └── id_zone → zones.id_zone

areas:
   └── id_management → managements.id_management
```

### Grafo Completo del Módulo Budget

```
zones ─────────< cost_centers >──────── areas
                      │
         ┌────────────┼────────────┐
         v            v            v
 actual_expenses  actual_costs  budget_lines ──> budgets
                                   │                │
                                   │          (self-ref: parent_budget_id)
                                   │                │
                                   │         budget_scenarios
                                   │
customers ──< accounts_receivable >── invoices
                     │                │
                payment_ledger ───────┘
```

### 2.1 Nuevos Modelos Generales

#### `Zone` → Tabla: `zones`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_zone` | Integer | PK, index |
| `zone_name` | String(80) | NOT NULL |
| `zone_code` | String(10) | unique, index, NOT NULL |

#### `Management` → Tabla: `managements`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_management` | Integer | PK, index |
| `management_name` | String(100) | NOT NULL |
| `management_code` | String(10) | unique, index |

#### `Area` → Tabla: `areas`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_area` | Integer | PK, index |
| `area_name` | String(100) | NOT NULL |
| `area_code` | String(10) | unique, index |
| `id_management` | Integer | FK → `managements.id_management` |

### 2.2 Modificación en `Department`

| Campo | Acción |
|---|---|
| `zone` (String) | ❌ Eliminado |
| `id_zone` | ✅ Agregado FK → `zones.id_zone` |

### 2.3 `CostCenter` → Tabla: `cost_centers`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_cost_center` | Integer | PK, index |
| `cost_center_code` | String(20) | unique, index, NOT NULL |
| `cost_center_name` | String(120) | NOT NULL |
| `id_zone` | Integer | FK → `zones.id_zone` |
| `id_area` | Integer | FK → `areas.id_area` |
| `id_line` | Integer | FK → `lines.id_line` |
| `is_active` | Boolean | server_default="True" |
| `description` | Text | nullable |

### 2.2 `ActualExpense` → Tabla: `actual_expenses`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_actual_expense` | Integer | PK, index |
| `id_cost_center` | Integer | FK → `cost_centers.id_cost_center`, NOT NULL |
| `expense_date` | Date | NOT NULL |
| `expense_type` | String(60) | NOT NULL |
| `description` | Text | nullable |
| `amount` | Float | NOT NULL, server_default="0" |
| `source_file` | String(200) | nullable |
| `created_at` | DateTime | server_default=func.now() |

### 2.3 `ActualCost` → Tabla: `actual_costs`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_actual_cost` | Integer | PK, index |
| `id_cost_center` | Integer | FK → `cost_centers.id_cost_center`, NOT NULL |
| `cost_date` | Date | NOT NULL |
| `cost_type` | String(60) | NOT NULL |
| `description` | Text | nullable |
| `amount` | Float | NOT NULL, server_default="0" |
| `source_file` | String(200) | nullable |
| `created_at` | DateTime | server_default=func.now() |

### 2.4 `Budget` → Tabla: `budgets`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_budget` | Integer | PK, index |
| `budget_name` | String(120) | NOT NULL |
| `budget_year` | Integer | NOT NULL |
| `budget_period` | String(20) | NOT NULL |
| `id_department` | Integer | FK → `departments.id_department` |
| `status` | String(20) | server_default="'draft'" |
| `is_scenario` | Boolean | server_default="False" |
| `parent_budget_id` | Integer | FK → `budgets.id_budget` (self-ref) |
| `created_at` | DateTime | server_default=func.now() |
| `updated_at` | DateTime | server_default=func.now(), onupdate=func.now() |

### 2.5 `BudgetLine` → Tabla: `budget_lines`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_budget_line` | Integer | PK, index |
| `id_budget` | Integer | FK → `budgets.id_budget`, NOT NULL |
| `id_cost_center` | Integer | FK → `cost_centers.id_cost_center`, NOT NULL |
| `line_type` | Enum(LineTypeEnum) | NOT NULL (income/expense) |
| `month` | Integer | NOT NULL (1-12) |
| `projected_amount` | Float | NOT NULL, server_default="0" |
| `description` | Text | nullable |

### 2.6 `AccountReceivable` → Tabla: `accounts_receivable`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_account_receivable` | Integer | PK, index |
| `id_customer` | Integer | FK → `customers.id_customer` |
| `id_invoice` | Integer | FK → `invoices.id_invoice` |
| `document_number` | String(50) | NOT NULL |
| `due_date` | Date | NOT NULL |
| `total_amount` | Float | NOT NULL, server_default="0" |
| `paid_amount` | Float | server_default="0" |
| `balance` | Float | server_default="0" |
| `status` | String(20) | server_default="'open'" |
| `aging_bucket` | String(20) | nullable (current, 30, 60, 90+) |
| `source_file` | String(200) | nullable |
| `created_at` | DateTime | server_default=func.now() |

### 2.7 `PaymentLedger` → Tabla: `payment_ledger`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_payment_ledger` | Integer | PK, index |
| `id_account_receivable` | Integer | FK → `accounts_receivable.id_account_receivable`, NOT NULL |
| `payment_date` | Date | NOT NULL |
| `payment_amount` | Float | NOT NULL, server_default="0" |
| `payment_method` | String(40) | nullable |
| `reference_number` | String(60) | nullable |
| `id_invoice` | Integer | FK → `invoices.id_invoice` |
| `source_file` | String(200) | nullable |
| `created_at` | DateTime | server_default=func.now() |

### 2.8 `BudgetScenario` → Tabla: `budget_scenarios`

| Campo | Tipo | Restricciones |
|---|---|---|
| `id_budget_scenario` | Integer | PK, index |
| `scenario_name` | String(120) | NOT NULL |
| `id_budget` | Integer | FK → `budgets.id_budget`, NOT NULL |
| `scenario_type` | String(40) | NOT NULL |
| `parameters` | JSON | nullable |
| `results` | JSON | nullable |
| `is_active` | Boolean | server_default="True" |
| `created_at` | DateTime | server_default=func.now() |
| `updated_at` | DateTime | server_default=func.now(), onupdate=func.now() |

---

## 3. Schemas Pydantic

### Resumen de Schemas por Entidad

| Entidad | Schemas |
|---|---|
| Zone | `ZoneBase`, `ZoneCreate`, `Zone` |
| Management | `ManagementBase`, `ManagementCreate`, `Management` |
| Area | `AreaBase`, `AreaCreate`, `Area` |
| CostCenter | `CostCenterBase`, `CostCenterCreate`, `CostCenter` |
| ActualExpense | `ActualExpenseBase`, `ActualExpenseCreate`, `ActualExpense` |
| ActualCost | `ActualCostBase`, `ActualCostCreate`, `ActualCost` |
| Budget | `BudgetBase`, `BudgetCreate`, `Budget`, `BudgetFull` |
| BudgetLine | `BudgetLineBase`, `BudgetLineCreate`, `BudgetLine`, `BudgetLineFull` |
| AccountReceivable | `AccountReceivableBase`, `AccountReceivableCreate`, `AccountReceivable`, `AccountReceivableFull` |
| PaymentLedger | `PaymentLedgerBase`, `PaymentLedgerCreate`, `PaymentLedger` |
| BudgetScenario | `BudgetScenarioBase`, `BudgetScenarioCreate`, `BudgetScenario` |

### Schemas Analíticos (Response-only)

| Schema | Campos |
|---|---|
| `BudgetVsActual` | `id_cost_center`, `cost_center_code`, `cost_center_name`, `month`, `budgeted_amount`, `actual_amount`, `variance`, `variance_percentage` |
| `CashFlowProjection` | `month`, `expected_inflows`, `expected_outflows`, `net_cash_flow`, `cumulative_cash_flow` |
| `BudgetTrackingSummary` | `id_budget`, `budget_name`, `total_budgeted`, `total_actual`, `total_variance`, `execution_percentage`, `by_month: List[BudgetVsActual]` |

---

## 4. Operaciones CRUD

### Resumen de Funciones CRUD por Entidad

| Entidad | Funciones |
|---|---|
| **Zone** | `create`, `get_by_id`, `get_by_code`, `get_all`, `update`, `delete` (6) |
| **Management** | `create`, `get_by_id`, `get_by_code`, `get_all`, `update`, `delete` (6) |
| **Area** | `create`, `get_by_id`, `get_by_code`, `get_filtered`, `update`, `delete` (6) |
| **CostCenter** | `create`, `get_by_id`, `get_by_code`, `get_all`, `update`, `delete` (6) |
| **ActualExpense** | `create`, `create_bulk`, `get_by_id`, `get_by_cost_center`, `get_filtered`, `update`, `delete` (7) |
| **ActualCost** | `create`, `create_bulk`, `get_by_id`, `get_by_cost_center`, `get_filtered`, `update`, `delete` (7) |
| **Budget** | `create`, `get_by_id`, `get_filtered`, `update`, `delete` (5) |
| **BudgetLine** | `create`, `create_bulk`, `get_by_id`, `get_by_budget`, `get_by_cost_center`, `update`, `delete` (7) |
| **AccountReceivable** | `create`, `create_bulk`, `get_by_id`, `get_filtered`, `update`, `delete` (6) |
| **PaymentLedger** | `create`, `create_bulk`, `get_by_id`, `get_by_account_receivable`, `get_filtered`, `update`, `delete` (7) |
| **BudgetScenario** | `create`, `get_by_id`, `get_by_budget`, `get_filtered`, `update`, `delete` (6) |

**Total: 69 funciones CRUD** (incluye 5 bulk insert para ETL)

---

## 5. Endpoints API

### Routers Generales (Nuevos)

| Router | Prefix | Endpoints |
|---|---|---|
| `zone` | `/zone` | 5 |
| `management` | `/management` | 5 |
| `area` | `/area` | 5 |

**Total: 15 endpoints generales** (todos protegidos con `get_current_user`)

### Router Budget: `budget = APIRouter(prefix="/budget")`

| Sub-router | Prefix | Endpoints |
|---|---|---|
| `cost_center_router` | `/budget/cost-center` | 5 |
| `actual_expense_router` | `/budget/actual-expense` | 6 |
| `actual_cost_router` | `/budget/actual-cost` | 6 |
| `budget_router` | `/budget/` | 6 |
| `budget_line_router` | `/budget/line` | 5 |
| `account_receivable_router` | `/budget/account-receivable` | 5 |
| `payment_ledger_router` | `/budget/payment-ledger` | 6 |
| `budget_scenario_router` | `/budget/scenario` | 6 |
| `upload_router` | `/budget/upload` | 5 |
| `analytics_router` | `/budget/analytics` | 4 |

**Total: 54 endpoints budget** (todos protegidos con `get_current_user`)

**Total General: 69 endpoints** (15 generales + 54 budget)

### 5.1 Endpoints CRUD Completados (65 endpoints)

Operaciones estándar GET/POST/PUT/DELETE para cada entidad con:
- Validación de existencia (404)
- Validación de unicidad (409) donde aplica
- Validación de FK antes de crear
- Filtros por query params con paginación (skip/limit)

### 5.2 Endpoints ETL Upload (5 endpoints - TODO)

| Método | Ruta | Archivo Fuente | Estado |
|---|---|---|---|
| POST | `/budget/upload/cost-centers` | Catálogo CECOs | TODO |
| POST | `/budget/upload/actual-expenses` | LibroAuxiliarCECO.xlsx | TODO |
| POST | `/budget/upload/actual-costs` | CostosFinal.xlsx | TODO |
| POST | `/budget/upload/accounts-receivable` | EstadoCuenta306090.xlsx (skiprows=3) | TODO |
| POST | `/budget/upload/payment-ledger` | RecibosDePago.xlsx | TODO |

### 5.3 Endpoints Analíticos (4 endpoints - TODO)

| Método | Ruta | Response | Estado |
|---|---|---|---|
| GET | `/budget/analytics/cash-flow-projection` | `List[CashFlowProjection]` | TODO |
| GET | `/budget/analytics/budget-vs-actual` | `List[BudgetVsActual]` | TODO |
| GET | `/budget/analytics/tracking/{id_budget}` | `BudgetTrackingSummary` | TODO |
| POST | `/budget/analytics/clone-for-scenario/{id_budget}` | `Budget` | TODO |

---

## 6. Tubería de Ingesta de Datos (*ETL Pipeline*)

### `app/utils/templates/budgetTemplates.py` - Clase `BudgetTemplates`

**Constructor:** `__init__(self, file: BytesIO)` - Recibe archivo en memoria.

#### Métodos Públicos (ETL por archivo)

| Método | Archivo Fuente | Tabla Destino | Notas |
|---|---|---|---|
| `process_cost_centers()` | Catálogo Excel | `cost_centers` | Catálogo maestro |
| `process_costos_final()` | CostosFinal.xlsx | `actual_costs` | Mapeo por `codigo_ceco` |
| `process_libro_auxiliar_ceco()` | LibroAuxiliarCECO.xlsx | `actual_expenses` | Mapeo por `codigo_ceco` |
| `process_estado_cuenta()` | EstadoCuenta306090.xlsx | `accounts_receivable` | **skiprows=3**, aging buckets |
| `process_recibos_de_pago()` | RecibosDePago.xlsx | `payment_ledger` | Mapeo collections |
| `dataframe_to_records()` | Genérico | - | DataFrame → List[Dict], NaN/NaT → None |

#### Métodos Privados (Helpers)

| Método | Descripción |
|---|---|
| `_clean_column_names()` | Normaliza: strip, lowercase, espacios/guiones → underscore |
| `_cast_numeric_columns(columns)` | `pd.to_numeric(errors="coerce")` |
| `_cast_date_columns(columns)` | `pd.to_datetime(errors="coerce")` |
| `_compute_aging_buckets()` | current (≤0 días), 30 (1-30), 60 (31-60), 90 (61-90), 90+ (>90) |

---

## 7. Motor Financiero (*Financial Engine*)

### `app/services/budgetEngine.py` - Clase `BudgetEngine`

**Constructor:** `__init__(self, db: Session)` - Recibe sesión SQLAlchemy.

| Método | Parámetros | Retorna | Estado |
|---|---|---|---|
| `project_cash_flow()` | `budget_year: int, id_budget: Optional[int]` | `List[Dict]` | TODO |
| `get_budget_vs_actual()` | `id_budget: int, id_cost_center: Optional[int], month: Optional[int]` | `List[Dict]` | TODO |
| `get_budget_tracking_summary()` | `id_budget: int` | `Dict` | TODO |
| `clone_budget_for_scenario()` | `id_budget: int, scenario_name: str` | `Optional[BudgetModel]` | TODO |
| `apply_scenario_parameters()` | `id_budget_scenario: int, parameters: Dict` | `Dict` | TODO |
| `compare_scenarios()` | `id_budget_base: int, id_scenario_a: int, id_scenario_b: Optional[int]` | `Dict` | TODO |
| `get_monthly_expense_summary()` | `id_cost_center: Optional[int], year: Optional[int]` | `List[Dict]` | TODO |
| `get_cost_center_summary()` | `year: Optional[int]` | `List[Dict]` | TODO |

**Total: 8 métodos de lógica financiera (esqueleto con docstrings)**

---

## 8. Registraciones en `__init__.py` Principales

| Archivo | Import | Estado |
|---|---|---|
| `app/models/__init__.py` | `from .zone import Zone`, `from .management import Management`, `from .area import Area`, `from .budget import (...)` | ✅ |
| `app/schemas/__init__.py` | `from .zone import Zone, ZoneCreate`, `from .management import Management, ManagementCreate`, `from .area import Area, AreaCreate`, `from .budget import (...)` | ✅ |
| `app/crud/__init__.py` | `from .zone import *`, `from .management import *`, `from .area import *`, `from .budget import *` | ✅ |
| `app/api/__init__.py` | `from .zone import zone`, `from .management import management`, `from .area import area`, `from .budget import budget` | ✅ |
| `app/main.py` | `app.include_router(zone)`, `app.include_router(management)`, `app.include_router(area)`, `app.include_router(budget)` | ✅ |

---

## 9. Resumen de Cobertura y Estado

| Capa | Archivos | Funciones/Endpoints | Estado |
|---|---|---|---|
| **Modelos Generales** | 3 nuevos (`zone.py`, `management.py`, `area.py`) | 3 tablas SQLAlchemy | ✅ COMPLETO |
| **Modelos Budget** | 8 + `__init__.py` | 8 tablas SQLAlchemy | ✅ COMPLETO |
| **Schemas Generales** | 3 nuevos | 6 schemas Pydantic | ✅ COMPLETO |
| **Schemas Budget** | 9 + `__init__.py` | 22 schemas Pydantic | ✅ COMPLETO |
| **CRUD Generales** | 3 nuevos | 18 funciones | ✅ COMPLETO |
| **CRUD Budget** | 8 + `__init__.py` | 51 funciones (incluye 5 bulk) | ✅ COMPLETO |
| **API - Generales** | 3 nuevos | 15 endpoints | ✅ COMPLETO |
| **API - Budget CRUD** | 8 archivos | 50 endpoints | ✅ COMPLETO |
| **API - Upload** | 1 archivo (`upload.py`) | 5 endpoints ETL | ⏳ TODO (placeholders) |
| **API - Analytics** | 1 archivo (`analytics.py`) | 4 endpoints analíticos | ⏳ TODO (stubs) |
| **ETL Templates** | 1 archivo (`budgetTemplates.py`) | 5 métodos + 4 helpers | ✅ COMPLETO (estructura) |
| **Budget Engine** | 1 archivo (`budgetEngine.py`) | 8 métodos financieros | ⏳ TODO (esqueleto) |
| **Registraciones** | 5 archivos `__init__.py` + `main.py` | 4 puntos de registro | ✅ COMPLETO |

**Total archivos de código fuente: 47 archivos** (35 anteriores + 12 nuevos)

---

## 10. SQL para Modificación de Base de Datos

```sql
-- 1. Crear tabla zones
CREATE TABLE zones (
    id_zone SERIAL PRIMARY KEY,
    zone_name VARCHAR(80) NOT NULL,
    zone_code VARCHAR(10) UNIQUE NOT NULL
);

-- 2. Agregar id_zone a departments
ALTER TABLE departments 
ADD COLUMN id_zone INTEGER REFERENCES zones(id_zone);

CREATE INDEX idx_departments_id_zone ON departments(id_zone);

-- 3. Migrar datos del campo zone (String) a id_zone
INSERT INTO zones (zone_name, zone_code)
SELECT DISTINCT zone, LEFT(zone, 10) 
FROM departments 
WHERE zone IS NOT NULL AND zone != '';

UPDATE departments d
SET id_zone = z.id_zone
FROM zones z
WHERE d.zone = z.zone_name;

-- 4. Eliminar campo zone (String) de departments
ALTER TABLE departments DROP COLUMN zone;

-- 5. Crear tabla managements
CREATE TABLE managements (
    id_management SERIAL PRIMARY KEY,
    management_name VARCHAR(100) NOT NULL,
    management_code VARCHAR(10) UNIQUE
);

-- 6. Crear tabla areas
CREATE TABLE areas (
    id_area SERIAL PRIMARY KEY,
    area_name VARCHAR(100) NOT NULL,
    area_code VARCHAR(10) UNIQUE,
    id_management INTEGER REFERENCES managements(id_management)
);

CREATE INDEX idx_areas_id_management ON areas(id_management);

-- 7. Modificar cost_centers: eliminar id_department, agregar id_zone e id_area
ALTER TABLE cost_centers ADD COLUMN id_zone INTEGER REFERENCES zones(id_zone);
ALTER TABLE cost_centers ADD COLUMN id_area INTEGER REFERENCES areas(id_area);

CREATE INDEX idx_cost_centers_id_zone ON cost_centers(id_zone);
CREATE INDEX idx_cost_centers_id_area ON cost_centers(id_area);

ALTER TABLE cost_centers DROP CONSTRAINT IF EXISTS cost_centers_id_department_fkey;
ALTER TABLE cost_centers DROP COLUMN id_department;
```

---

## 11. Próximos Pasos de Implementación

1. **Implementar lógica de endpoints ETL** (`upload.py`) - Conectar `BudgetTemplates` con bulk inserts del CRUD
2. **Implementar motor financiero** (`budgetEngine.py`) - Queries de agregación reales
3. **Implementar lógica de clonación** para escenarios what-if (`clone_budget_for_scenario`)
4. **Añadir RBAC granular** - Validación de roles específicos para operaciones financieras
5. **Probar creación de tablas** - `docker compose -f docker-compose-dev.yaml up` para verificar `Base.metadata.create_all`
