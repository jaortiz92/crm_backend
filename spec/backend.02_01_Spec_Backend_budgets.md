# Especificación Técnica: Cuentas por Pagar (Accounts Payable)

> **Estado:** ✅ Implementado (2026-08-24)

## 1. Modelado de Base de Datos (*Database Schema*)
Se implementará una relación de uno a muchos (*One-to-Many*) para separar la obligación principal de las múltiples transacciones de pago.

### Tabla: `accounts_payable` (La Obligación)
Esta tabla registra la deuda total consolidada con el proveedor asiático o logístico.

| Campo | Tipo | Restricciones / Notas |
|---|---|---|
| `id_account_payable` | Integer | PK, index |
| `id_cost_center` | Integer | FK → `cost_centers.id_cost_center` |
| `supplier_name` | String(120) | NOT NULL |
| `total_amount` | Numeric(15,2) | NOT NULL |
| `balance` | Numeric(15,2) | NOT NULL (*Balance due* / Saldo pendiente) |
| `due_date` | Date | NOT NULL (*Deadline* / Fecha límite) |
| `status` | Enum | Valores: `open`, `partial`, `paid` |

### Tabla: `payable_ledger` (Los Desembolsos)
Esta tabla actúa como el historial transaccional (*transaction log*), permitiendo registrar múltiples giros para una misma factura.

| Campo | Tipo | Restricciones / Notas |
|---|---|---|
| `id_payable_ledger` | Integer | PK, index |
| `id_account_payable` | Integer | FK → `accounts_payable.id_account_payable` |
| `payment_date` | Date | NOT NULL (*Date of transaction* / Fecha de salida) |
| `amount_paid` | Numeric(15,2) | NOT NULL |
| `payment_reference` | String(60) | Opcional (Ej. Número de transferencia swift) |

---

## 2. Ajustes en el Backend (*Backend Adjustments*)
*   **Modelos y Schemas:** Crear los archivos `app/models/budget/accountPayable.py` y `app/models/budget/payableLedger.py`, respetando el uso de `psycopg2` y SQLAlchemy sincrónico.
*   **Reglas de Validación (Pydantic):** Al registrar un nuevo pago en el *ledger*, el backend debe validar estrictamente que el `amount_paid` no supere el `balance` actual de la obligación.
*   **Disparadores Lógicos (*Triggers*):** Al insertar un registro en `payable_ledger`, el sistema debe actualizar automáticamente el `balance` y el `status` en la tabla padre `accounts_payable`.

---

## 3. Impacto en el Motor Financiero (*Financial Engine*)
*   **Actualización del Cash Flow:** Refactorizar el método `project_cash_flow()` en el archivo `budgetEngine.py`.
*   **Manejo de Egresos (*Cash Outflows*):** El sistema leerá el `balance` pendiente en `accounts_payable` y lo proyectará como una salida de dinero en el mes correspondiente a su `due_date`.
*   **Prevención de Duplicados (*Double Counting*):** Para evitar distorsiones, el motor debe anular las proyecciones teóricas de `budget_lines` (cuando coincidan en mes y centro de costo) si la obligación ya es un hecho contable real en `accounts_payable`.

---

## 4. Implementación Realizada (*Implementation Details*)

### 4.1 Archivos Creados

| Capa | Archivo | Descripción |
|---|---|---|
| **Model** | `app/models/budget/accountPayable.py` | Modelo `AccountPayable` con enum `PayableStatusEnum` (open/partial/paid) |
| **Model** | `app/models/budget/payableLedger.py` | Modelo `PayableLedger` con FK a `accounts_payable` |
| **Schema** | `app/schemas/budget/accountPayable.py` | Schemas: `AccountPayableBase`, `AccountPayableCreate`, `AccountPayable`, `AccountPayableFull` |
| **Schema** | `app/schemas/budget/payableLedger.py` | Schemas: `PayableLedgerBase`, `PayableLedgerCreate`, `PayableLedger` |
| **CRUD** | `app/crud/budget/accountPayable.py` | Operaciones CRUD con inicialización automática de `balance = total_amount` |
| **CRUD** | `app/crud/budget/payableLedger.py` | CRUD con validación de balance y actualización automática del padre |
| **API** | `app/api/budget/accountPayable.py` | Endpoints REST en `/budget/account-payable/` |
| **API** | `app/api/budget/payableLedger.py` | Endpoints REST en `/budget/payable-ledger/` |

### 4.2 Archivos Modificados

| Archivo | Cambio |
|---|---|
| `app/models/budget/__init__.py` | Registrados `AccountPayable`, `PayableLedger` |
| `app/schemas/budget/__init__.py` | Registrados todos los schemas nuevos |
| `app/crud/budget/__init__.py` | Wildcard imports para nuevos CRUD |
| `app/api/budget/__init__.py` | Registrados routers con prefijos `/account-payable` y `/payable-ledger` |
| `app/models/__init__.py` | Exportación top-level de nuevos modelos |
| `app/schemas/__init__.py` | Exportación top-level de nuevos schemas |
| `app/services/budgetEngine.py` | Refactorizado `project_cash_flow()` con lógica de egresos y prevención de duplicados |
| `app/api/budget/analytics.py` | Conectado endpoint `/analytics/cash-flow-projection` al `BudgetEngine` |

### 4.3 Endpoints API Creados

#### Accounts Payable (`/budget/account-payable/`)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Lista cuentas por pagar con filtros opcionales (cost_center, status, due_date) |
| `GET` | `/{id_account_payable}` | Obtiene una cuenta por pagar con sus entradas de ledger |
| `POST` | `/` | Crea nueva cuenta por pagar (balance se inicializa = total_amount) |
| `PUT` | `/{id_account_payable}` | Actualiza cuenta por pagar existente |
| `DELETE` | `/{id_account_payable}` | Elimina cuenta por pagar |

#### Payable Ledger (`/budget/payable-ledger/`)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Lista entradas de ledger con filtros opcionales |
| `GET` | `/{id_payable_ledger}` | Obtiene una entrada de ledger |
| `GET` | `/account-payable/{id_account_payable}` | Lista todas las entradas para una cuenta por pagar |
| `POST` | `/` | Registra pago (valida amount_paid <= balance, actualiza padre) |
| `DELETE` | `/{id_payable_ledger}` | Elimina entrada de ledger |

### 4.4 Lógica del Motor Financiero (`BudgetEngine.project_cash_flow()`)

```python
def project_cash_flow(budget_year: int, id_budget: Optional[int] = None):
    """
    Flujo de implementación:
    
    1. INFLOWS: Agrupa accounts_receivable.balance por mes de due_date
    2. OUTFLOWS (reales): Agrupa accounts_payable.balance por mes de due_date
       - Construye set de claves (month, cost_center) para detección de duplicados
    3. OUTFLOWS (teóricos): Consulta budget_lines tipo 'expense'
       - EXCLUYE entradas donde (month, cost_center) ya existe en accounts_payable
    4. Retorna proyección mensual con cumulative_cash_flow
    """
```

### 4.5 Validaciones Implementadas

1. **Validación de pago excedido:** En `create_payable_ledger()`, se lanza `HTTPException 400` si `amount_paid > balance`.

2. **Actualización automática de estado:**
   - Si `balance == 0` → `status = "paid"`
   - Si `balance > 0` → `status = "partial"`

3. **Prevención de double counting:** El motor excluye proyecciones teóricas de `budget_lines` cuando existe una obligación real en `accounts_payable` para el mismo (mes, centro de costo).