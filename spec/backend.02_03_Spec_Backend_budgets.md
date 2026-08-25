# Especificación Técnica: ETL para Carga de Presupuesto Inicial (Master Templates)

## 1. Visión General (*Overview*)
El sistema habilitará dos nuevos *endpoints* para la ingesta de las plantillas maestras en Excel. El objetivo es procesar estos archivos para generar automáticamente la carpeta del presupuesto (`budgets`) y sus respectivos rubros detallados mediante inserciones masivas (*bulk inserts*).

*   **Rutas a implementar:**
    *   `POST /budget/upload/budget-plan-income` (Plantilla de Ingresos)
    *   `POST /budget/upload/budget-plan-expense` (Plantilla de Gastos)

*   **Body del request (Form Data):**
    *   `budget_name` (String, requerido)
    *   `budget_year` (Integer, requerido)
    *   `budget_period` (String, requerido: "annual", "quarterly", "monthly")
    *   `id_department` (Integer, opcional)
    *   `file` (UploadFile, requerido)

---

## 2. Cambios en Base de Datos

### 2.1 Tabla `budget_lines` — Reemplazo de `month` por `budget_date` y `payment_date`

| Cambio | Columna Anterior | Columna Nueva | Tipo | Nullable |
| :--- | :--- | :--- | :--- | :--- |
| Reemplazo | `month` (Integer) | `budget_date` | Date | NOT NULL |
| Nuevo | — | `payment_date` | Date | Nullable |
| Nuevo | — | `id_collection` | Integer FK → `collections.id_collection` | Nullable |

*   **Lógica:** `budget_date` rastrea cuándo ocurre el gasto/ingreso (P&L). `payment_date` indica cuándo sale/entra el efectivo (Cash Flow).
*   **Nota:** La columna `description` (Text) ya existe y se usará para el campo "Concepto del Gasto" / "Observaciones Adicionales". No se crea un campo `detail` adicional.

### 2.2 Nueva tabla `line_payment_rules`

Tabla para definir las reglas de pago por línea de producto. Permite modelar pagos parciales antes y después de la facturación.

| Columna | Tipo | Nullable | Descripción |
| :--- | :--- | :--- | :--- |
| `id_line_payment_rule` | Integer (PK, auto) | NOT NULL | Clave primaria |
| `id_line` | Integer FK → `lines.id_line` | NOT NULL | Línea de producto |
| `payment_pct` | Float | NOT NULL | Porcentaje del pago (0-1). La suma de reglas por línea debe ser 1.0 |
| `payment_days` | Integer | NOT NULL | Días relativos a `budget_date`. Negativo = antes de facturación. Positivo = después |

*   **Ejemplo:** Si una línea tiene dos reglas:
    *   Regla 1: `payment_pct=0.30`, `payment_days=-30` → 30% se paga 30 días antes de la facturación
    *   Regla 2: `payment_pct=0.70`, `payment_days=0` → 70% se paga en la fecha de facturación
*   **Relación:** `Line.payment_rules = relationship("LinePaymentRule", backref="line")`

### 2.3 Migración SQL (manual, `create_all` no altera tablas existentes)

```sql
ALTER TABLE budget_lines ADD COLUMN budget_date DATE;
ALTER TABLE budget_lines ADD COLUMN payment_date DATE;
ALTER TABLE budget_lines ADD COLUMN id_collection INTEGER REFERENCES collections(id_collection);

UPDATE budget_lines
SET budget_date = make_date(budgets.budget_year, budget_lines.month, 1)
FROM budgets WHERE budget_lines.id_budget = budgets.id_budget;

ALTER TABLE budget_lines ALTER COLUMN budget_date SET NOT NULL;
ALTER TABLE budget_lines DROP COLUMN month;

CREATE TABLE line_payment_rules (
    id_line_payment_rule SERIAL PRIMARY KEY,
    id_line INTEGER NOT NULL REFERENCES lines(id_line),
    payment_pct FLOAT NOT NULL,
    payment_days INTEGER NOT NULL
);
```

---

## 3. Limpieza de Datos (*Data Cleansing* en Pandas)

Ambos formatos institucionales comparten una estructura de encabezado corporativo.
*   **Regla de Extracción:** El método en `BudgetTemplates` debe utilizar `pd.read_excel(..., skiprows=7)` para ignorar las primeras 7 filas y tomar la fila 8 como los encabezados reales (`columns`).
*   **Mapeo de IDs:** La columna "Centro de Costo" (ej. "410100 Administrativo General") debe procesarse haciendo un *split* del texto para extraer el código numérico y cruzarlo con `cost_centers.cost_center_code` y obtener el `id_cost_center`.
*   **Mapeo de Temporada:** La columna "Temporada" se cruza con `collections.short_collection_name` para obtener `id_collection`.

---

## 4. Mapeo: Plantilla de Ingresos (*Income Mapping*)

Para el archivo "Formato Solicitud Presupuesto Ingresos.xlsx".

| Columna Excel | Destino en `budget_lines` | Transformación / Regla de Negocio |
| :--- | :--- | :--- |
| `Centro de Costo` | `id_cost_center` | Split del texto → `cost_center_code` → búsqueda por `get_cost_center_by_code()`. |
| `Fecha de la Facturacion (Proyectada)` | `budget_date` | Parse a `Date`. |
| `Temporada` | `id_collection` | Búsqueda por `collections.short_collection_name`. |
| `Monto` | `projected_amount` | *Type casting* a numérico. |
| `Observaciones Adicionales` | `description` | Texto libre. |
| **N/A (Automático)** | `line_type` | Forzar valor a `'income'`. |
| **N/A (Automático)** | `behavior_type` | Forzar valor a `'fixed'`. |
| **Calculado** | `payment_date` | Se calcula usando `line_payment_rules` del `id_line` del cost center (ver sección 7). |

---

## 5. Mapeo: Plantilla de Gastos (*Expense Mapping*)

Para el archivo "Formato Solicitud Presupuesto Gastos.xlsx".

| Columna Excel | Destino en `budget_lines` | Transformación / Regla de Negocio |
| :--- | :--- | :--- |
| `Centro de Costo` | `id_cost_center` | Split del texto → `cost_center_code` → búsqueda por `get_cost_center_by_code()`. |
| `Fecha del Gasto (Proyectada)` | `budget_date` | Parse a `Date`. Afecta el Estado de Resultados (P&L). |
| `Fecha de Pago (Proyectada)` | `payment_date` | Parse a `Date`. Afecta el Flujo de Caja. |
| `Concepto del Gasto` | `description` | Texto libre. |
| `Temporada` | `id_collection` | Búsqueda por `collections.short_collection_name`. |
| `Comportamiento` | `behavior_type` | Diccionario de traducción estricto (Ver sección 5.1). |
| `Monto o Tasa Solicitado` | `projected_amount` / `variable_rate` | Depende del comportamiento (Ver sección 5.2). |
| **N/A (Automático)** | `line_type` | Forzar valor a `'expense'`. |

### 5.1 Traducción de Comportamientos (*Behavior Dictionary*)
El backend debe mapear los textos exactos de la lista desplegable del Excel a los Enums de la base de datos:
*   "Fijo" → `fixed`
*   "Variable por Facturación" → `variable_sales`
*   "Variable por Recaudo" → `variable_receivables`

### 5.2 Lógica Condicional de Montos (*Amount Logic*)
Al procesar la columna "Monto o Tasa Solicitado":
*   Si `behavior_type == 'fixed'`: El valor se guarda en `projected_amount` y `variable_rate` queda en `NULL`.
*   Si `behavior_type != 'fixed'`: El valor (tasa porcentual, 0-1) se guarda en `variable_rate` y `projected_amount` se fuerza a `0` (ya que el motor lo calculará dinámicamente).

---

## 6. Flujo de Inserción (*Execution Workflow*)

1.  **Creación de Cabecera:** Al recibir la petición, el sistema crea un nuevo registro en la tabla `budgets` con estado `draft` usando los datos del Form Data (`budget_name`, `budget_year`, `budget_period`, `id_department`).
2.  **Procesamiento ETL:** Se lee el Excel con `BudgetTemplates` aplicando `skiprows=7`, limpieza de columnas y mapeo de IDs.
3.  **Validación:** Si falta algún `id_cost_center` o `id_collection`, se hace *rollback* de la transacción y se retorna error `400 Bad Request` con detalle de los IDs no encontrados.
4.  **Cálculo de `payment_date` (solo Ingresos):** Para cada línea de ingreso, se calcula `payment_date` aplicando las reglas de `line_payment_rules` del `id_line` asociado al cost center (ver sección 7).
5.  **Bulk Insert:** Si la validación es exitosa, se utiliza `create_budget_lines_bulk()` para insertar todas las filas en `budget_lines` en una sola transacción SQL.
6.  **Transacción atómica:** Los pasos 1-5 ocurren dentro de una misma transacción. Si cualquier paso falla, se hace rollback completo.

---

## 7. Cálculo de `payment_date` para Ingresos

Para líneas de ingreso, `payment_date` no viene en el Excel sino que se calcula usando las reglas de pago de la línea de producto:

1.  Obtener el `id_line` del cost center (via `cost_centers.id_line`).
2.  Consultar `line_payment_rules` filtradas por ese `id_line`.
3.  Para cada regla, calcular la fecha de pago parcial: `budget_date + payment_days`.
4.  Si la línea tiene **una sola regla** con `payment_days=0`: `payment_date = budget_date`.
5.  Si la línea tiene **múltiples reglas**: se generan múltiples `budget_lines` (una por regla), cada una con su `payment_date` calculada y `projected_amount` proporcional al `payment_pct`.
6.  Si la línea **no tiene reglas** configuradas: `payment_date = budget_date` (default).

---

## 8. Refactor de `budgetEngine.py`

El motor financiero debe actualizarse para usar las nuevas columnas de tipo `Date`:

*   **Income inflows (P&L):** Agrupar por `extract('month', BudgetLineModel.budget_date)` y `extract('year', BudgetLineModel.budget_date)`.
*   **Expense outflows (Cash Flow):** Agrupar por `extract('month', BudgetLineModel.payment_date)`. Si `payment_date IS NULL`, usar `budget_date` como fallback.
*   **Budget tracking:** Reemplazar todas las referencias a `BudgetLineModel.month` por `extract('month', BudgetLineModel.budget_date)`.
*   **Schemas analíticos:** `BudgetVsActual.month` → `budget_month` (int derivado). `CashFlowProjection.month` → `payment_month` (int derivado).

---

## 9. Archivos a Modificar / Crear

| Acción | Archivo | Descripción |
| :--- | :--- | :--- |
| **Crear** | `app/models/linePaymentRule.py` | Modelo `LinePaymentRule` |
| **Modificar** | `app/models/budget/budgetLine.py` | Reemplazar `month` → `budget_date` + `payment_date` + `id_collection` |
| **Modificar** | `app/models/line.py` | Agregar relación `payment_rules` |
| **Modificar** | `app/models/__init__.py` | Registrar `LinePaymentRule` |
| **Modificar** | `app/models/budget/__init__.py` | (sin cambios, ya exporta BudgetLine) |
| **Crear** | `app/schemas/linePaymentRule.py` | Schemas `LinePaymentRuleBase/Create/Read` |
| **Modificar** | `app/schemas/budget/budgetLine.py` | Reemplazar `month` → `budget_date` + `payment_date` + `id_collection` |
| **Modificar** | `app/schemas/budget/budget.py` | Actualizar schemas analíticos |
| **Modificar** | `app/schemas/__init__.py` | Registrar schemas de `LinePaymentRule` |
| **Crear** | `app/crud/linePaymentRule.py` | CRUD para `LinePaymentRule` |
| **Modificar** | `app/crud/collection.py` | Agregar `get_collection_by_short_name()` |
| **Modificar** | `app/crud/budget/budgetLine.py` | Actualizar `order_by` a `budget_date` |
| **Modificar** | `app/crud/__init__.py` | (ya importa `budget.*`) |
| **Modificar** | `app/utils/templates/budgetTemplates.py` | Agregar métodos `process_budget_plan_income()` y `process_budget_plan_expense()` |
| **Modificar** | `app/utils/templates/__init__.py` | Exportar `BudgetTemplates` |
| **Modificar** | `app/api/budget/upload.py` | Agregar 2 endpoints de upload |
| **Modificar** | `app/services/budgetEngine.py` | Refactor de `month` → `budget_date`/`payment_date` |
