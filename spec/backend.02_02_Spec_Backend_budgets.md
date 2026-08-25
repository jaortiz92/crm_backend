# Especificación Técnica: Implementación de Gastos Variables (Cost Drivers)

## 1. Configuración Global de Constantes

Crear archivo `app/core/constants.py` con constantes globales para cálculos financieros.

```python
"""
Global constants for budget and financial calculations.
"""

TAX_RATE: float = 0.19  # IVA 19%
```

---

## 2. Actualización de Modelos: Tabla `budget_lines`

Para permitir simulaciones dinámicas y escalar el motor financiero, la tabla de líneas de presupuesto debe soportar comportamientos fijos y variables. Se utilizará el término `receivables` en lugar de `collection` para prevenir colisiones semánticas con el catálogo de ropa.

Se deben agregar dos nuevos campos a la entidad existente en `app/models/budget/budgetLine.py`.

| Nuevo Campo | Tipo | Restricciones / Notas |
|---|---|---|
| `behavior_type` | Enum | Valores permitidos: `fixed`, `variable_sales`, `variable_receivables`. Server default: `'fixed'` |
| `variable_rate` | Float | Nullable. Ej: `0.0300` para representar un 3% (*rate*) de comisión o flete. |

**Glosario de Comportamientos:** 
*   `fixed`: Gastos estables que no dependen de la operación (ej. arriendos).
*   `variable_sales`: Se dispara según el volumen de ventas facturadas (ej. fletes de despacho, empaques).
*   `variable_receivables`: Se dispara según el ingreso de efectivo o recaudo real (ej. comisiones a vendedores, pasarelas de pago).

---

## 3. Ajuste en Schemas Pydantic (*Data Validation*)

*   Actualizar `BudgetLineBase` en el archivo `app/schemas/budget/budgetLine.py`.
*   Incluir los nuevos campos asegurando la validación estricta del nuevo Enum.
*   Configurar `variable_rate` para que sea opcional (`Optional[float] = None`), ya que las líneas `fixed` no lo necesitarán.

---

## 4. Regla de Oro: Net Revenue Standard

**Regla Universal:** Todos los registros en la tabla `budget_lines` donde `line_type == 'income'` deben almacenarse de forma neta (**SIN IVA**).

### Impacto en el Motor Financiero:

#### A. Cálculo de Gastos Variables Proyectados (P&L Impact)
Dado que la proyección ya es neta, **NO** se requiere dividir por `(1 + tax_rate)`.
*   **Fórmula:** 
    `Gasto_Proyectado = variable_rate * (Σ projected_amount donde line_type == 'income')`

#### B. Proyección de Liquidez (Cash Flow Inflows)
Para las vistas de flujo de caja, el sistema debe simular el dinero real que entrará al banco (el cual incluye el IVA que paga el cliente).
*   **Fórmula:** 
    `Efectivo_Entrante = (Σ projected_amount) * (1 + TAX_RATE)`

#### C. Ejecución Real (Actuals) desde Facturación
Las facturas del CRM (`invoices`) mantienen su total bruto (`total_with_tax`). Cuando el motor mida la realidad, **SÍ** debe dividir por `(1 + TAX_RATE)` para encontrar la base comisionable real.

---

## 5. Lógica de Cálculo: Gastos Variables Dinámicos

El motor financiero (`budgetEngine.py`) debe aplicar las siguientes reglas al calcular los rubros de presupuesto que fluctúan según el rendimiento comercial.

### 5.1 Comportamiento: `variable_receivables` (Variable por Recaudo)

**Concepto:** Este gasto se genera únicamente cuando el dinero real entra al banco (*cash inflows*). Ideal para comisiones de vendedores (pago sobre recaudo efectivo) o comisiones de pasarelas de pago.

#### A. Para Proyectar el Futuro (*Forecast*)

**Fuentes de datos:**
1.  `accounts_receivable`: Sumar el `balance` (saldo bruto) de las facturas cuyo `due_date` cae en el mes objetivo.
2.  `budget_lines`: Sumar el `projected_amount` de todas las líneas donde `line_type == 'income'` para ese mismo mes (ya es NETO).

**Fórmula:**
```
Ingreso_Neto = Σ accounts_receivable.balance + Σ budget_lines.projected_amount (income)
Gasto_Proyectado = variable_rate * Ingreso_Neto
```

#### B. Para Medir la Realidad (*Actual Execution*)

**Fuente de datos:**
`payment_ledger` (Libro de pagos). Campo: `payment_amount`.

**Fórmula:**
```
Ingreso_Neto_Real = (Σ payment_amount donde payment_date es el mes evaluado) / (1 + TAX_RATE)
Gasto_Real = variable_rate * Ingreso_Neto_Real
```

---

### 5.2 Comportamiento: `variable_sales` (Variable por Ventas/Facturación)

**Concepto:** Este gasto se causa en el momento exacto en que se emite la factura o se confirma la venta (*billing*), independientemente de los plazos de pago. Ideal para rubros logísticos (fletes de despacho, empaques).

#### A. Para Proyectar el Futuro (*Forecast*)

**Fuente de datos:**
`budget_lines` (Líneas de presupuesto). Las proyecciones ya son NETAS (sin IVA).

**Fórmula:**
```
Gasto_Proyectado = variable_rate * (Σ projected_amount donde line_type == 'income')
```

#### B. Para Medir la Realidad (*Actual Execution*)

**Fuente de datos:**
Tabla `invoices` (Facturas del CRM). Campo: `total_with_tax` (bruto).

**Fórmula:**
```
Ingreso_Neto_Real = (Σ total_with_tax donde invoice_date es el mes evaluado) / (1 + TAX_RATE)
Gasto_Real = variable_rate * Ingreso_Neto_Real
```

---

## 6. Algoritmo de Cálculo en `project_cash_flow()`

El método `project_cash_flow()` en `app/services/budgetEngine.py` debe seguir este orden estricto:

1.  **Cálculo de Ingresos Base:**
    *   Sumar `accounts_receivable.balance` por mes (recaudo esperado bruto).
    *   Sumar `budget_lines.projected_amount` donde `line_type == 'income'` (ingresos netos).
    *   Para cash flow: `Efectivo_Entrante = (Σ ingresos netos) * (1 + TAX_RATE)`

2.  **Procesamiento de Gastos Fijos:**
    *   Sumar `projected_amount` donde `behavior_type == 'fixed'` y `line_type == 'expense'`.

3.  **Procesamiento Dinámico (Variable Costs):**
    *   **`variable_sales`:**
        ```
        base_ventas = Σ budget_lines.projected_amount (line_type == 'income')
        gasto_variable = variable_rate * base_ventas
        ```
    *   **`variable_receivables`:**
        ```
        base_recaudo = Σ accounts_receivable.balance + Σ budget_lines.projected_amount (income)
        gasto_variable = variable_rate * base_recaudo
        ```

4.  **Asignación al Vuelo:**
    *   Calcular gastos variables en memoria del servidor durante la consulta.
    *   Sumar al total de egresos (`outflows`).
    *   El gasto responde proporcionalmente al desempeño comercial en tiempo real.

---

## 7. Consideraciones de Implementación

### Import de Constantes
```python
from app.core.constants import TAX_RATE
```

### Validaciones en Schemas
*   `variable_rate` debe ser requerido cuando `behavior_type != 'fixed'`.
*   Validar que `variable_rate >= 0` y `variable_rate <= 1` (0% a 100%).

### Migración de Base de Datos
*   El proyecto usa `Base.metadata.create_all()` (no Alembic).
*   Para agregar columnas a tabla existente `budget_lines`:
    *   Opción A: Script SQL manual `ALTER TABLE`
    *   Opción B: Drop y recreate (pérdida de datos)
*   **Recomendación:** Documentar script SQL para producción.

### Clonación de Escenarios
*   El método `clone_budget_for_scenario()` debe copiar los nuevos campos (`behavior_type`, `variable_rate`).
*   Actualmente es TODO en `budgetEngine.py`.
