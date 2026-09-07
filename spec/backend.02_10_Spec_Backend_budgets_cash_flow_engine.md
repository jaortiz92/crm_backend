# Especificación Técnica: Budget Engine — Pilar 2 (Flujo de Caja / Cash Flow)

| Campo | Valor |
| :--- | :--- |
| **Documento** | Spec Motor Financiero — Pilar 2 (curva de liquidez: caja real + proyección de recaudos y pagos) |
| **Módulo** | `budget` -> servicio `BudgetEngine.get_cash_flow()` + endpoint `GET /budget/analytics/cash-flow` (cero tablas nuevas, cero DDL) |
| **Versión** | 1.0 |
| **Fecha** | 2026-09-07 |
| **Estado** | **Aprobada (2026-09-07) — implementada y verificada (2026-09-07)** |
| **Origen** | HSpec Pilar 2 (stakeholder) + sesión interactiva de definición (Decisiones D-1..D-7; A-3 rechazado por stakeholder con argumentos de liquidez) |
| **Patrón** | Capa de agregación de solo lectura (time-series en memoria, cero persistencia) + parámetros de experimentación `outflow_source` / `overdue_as` |
| **Fuentes analizadas** | `app/models/budget/paymentLedger.py`, `accountReceivable.py`, `accountPayable.py`, `payableLedger.py`, `budgetLine.py`, `app/crud/budget/payableLedger.py` (descuento automático de balance), `app/crud/budget/accountReceivable.py` (settle), `app/api/budget/upload.py` (ETL Recibos), `app/services/budgetEngine.py` (`project_cash_flow` legado), `app/api/budget/analytics.py`, `app/models/credit.py`; verificación de datos reales en BD dev (419 filas payment_ledger 2022→2026-03-31; AR/AP/payable_ledger/credits en 0 filas) |

> **Correcciones frente al HSpec base** (hallazgos verificados en código + datos):
> 1. **`outstanding_balance` no existe.** La columna real es `accounts_receivable.balance` (Float, neto: el ETL/settle descuenta pagos). El contrato usa el nombre real; `outstanding_balance` queda como alias semántico del HSpec. (§4.2)
> 2. **Las salidas del ledger ya llegan negativas**: `cash_flow='out'` con `payment_amount < 0` (verificado: 81 filas, −367.856.681,92; las 116 `in` suman +508.861.452). El motor **normaliza signos con `abs()` en la fuente** (BR-23): si el ETL capturara un `out` positivo, el payload igual lo reporta negativo. Nunca se re-signa dos veces.
> 3. **Acción-2 respondida por esquema y decisión de stakeholder (2026-09-07)**: SÍ existe tabla de obligaciones (`accounts_payable` + `payable_ledger`). Regla aprobada: parámetro `outflow_source` ∈ {`budget`, `ap`, `both`} default `both` **sin deduplicación**, con warnings de solape (D-1). `payable_ledger` NO entra en el cálculo: `create_payable_ledger` descuenta `accounts_payable.balance` automáticamente (verificado, línea 46 del CRUD) — restar los pagos otra vez sería doble conteo.
> 4. **`status` de AP/AR no es gobernable**: `create_payable_ledger` escribe literales minúsculos (`'paid'`/`'partial'`) que no coinciden con los nombres del Enum (`OPEN/PARTIAL/PAID`); filtro del motor es **siempre `balance > 0`**, nunca `status` (§13; bug preexistente registrado como ticket aparte, patrón I-7 de 02_09).
> 5. **`credits` queda fuera** (D-6/BR-36): cartera a plazo sin fecha de vencimiento (solo `term`/`last_payment_date`) y con riesgo de doble conteo contra el snapshot de Estado de Cuenta que ya alimenta AR.
> 6. **Sin IVA en la proyección** (D-5): `accounts_receivable.balance` es valor de documento (IVA incluido) y el HSpec pide `projected_amount` tal cual. La convención `(1 + TAX_RATE)` del `project_cash_flow` legado NO se replica ni se unifica (no-regresión; ver §8.4).

## 0. Registro de Decisiones (Decision Log)

| ID | Decisión | Origen |
| :-- | :--- | :--- |
| **D-1** | **Salidas proyectadas paramétricas**: `outflow_source` ∈ {`budget`, `ap`, `both`} (default `both`). En `both` no se deduplica presupuesto vs. deuda AP; el motor emite un `meta.warnings` por cada `(id_cost_center, bucket)` donde ambas fuentes proyectan al mismo tiempo (monto de cada lado). Fundamento stakeholder: excluir la deuda pendiente **deflacta** las salidas (un gasto puede haber desaparecido del presupuesto por falta de liquidez, pero la obligación sigue viva); el riesgo opuesto (inflar por doble conteo) queda **visible y auditable**, no silencioso. | Rechazo A-3 (2026-09-07) → opción 4 |
| **D-2** | **Deuda vencida (AP `due_date < cutoff`) paramétrica**: `overdue_as` ∈ {`clamp_cutoff`, `first_bucket`, `exclude`} (default `clamp_cutoff` = la deuda se ancla al bucket del corte, semántica "se paga al primer momento en que haya liquidez"). El total clampado/excluido se publica en `meta.overdue_outflows`. | Pregunta 2 de la sesión → opción 4 |
| **D-3** | **Punto de inflexión (Acción-1 del HSpec)**: `cutoff = date.today()` del servidor; bucket con `end < cutoff` ⇒ `status:"actual"`; si no ⇒ `"projected"` (el bucket del día del corte es `projected`). Un bucket que cruza el corte contiene **solo** real del ledger (las proyecciones se anclan a `>= cutoff` por construcción ⇒ cero doble cuenta). Parámetro opcional `cutoff_date` habilita análisis as-of y hace determinístico el smoke test. | A-1 aceptado + refinado en sesión |
| **D-4** | **Saldo inicial**: si llega `initial_balance`, manda (base real de banco); si no, se deriva como `SUM(CASH)` del ledger con `payment_date < date_from` (base *ledger-relativa*) y se emite warning de origen. `meta.initial_balance_source` ∈ {`provided`, `derived_from_ledger`}. | A-5 aceptado |
| **D-5** | **Cifras de caja tal cual**: sin aplicar `TAX_RATE`. Supuesto de negocio: gerencia captura gastos del presupuesto con IVA incluido (son pagos reales). El legado `(1+TAX_RATE)` no se toca ni se imita. | A-7 aceptado |
| **D-6** | **Acción-3 respondida**: los buckets cero-filled se generan **en Python** (helper `_cash_buckets`), no con `generate_series` de PostgreSQL: mantiene el estilo legacy `db.query` sin SQL crudo del proyecto y el motor 100 % testeable igual que `get_pnl`. | A-4 aceptado |
| **D-7** | **Selección de presupuesto** = reutiliza D-3 de la spec 02_09 (activo, no escenario, `budget_year = year(date_to)`, menor id; `id_budget` explícito manda con warning de escenario). Diferencia consciente: ausencia de presupuesto ⇒ **salidas proyectadas 0.0** (en liquidez "sin plan" sí significa cero) y warning, nunca null. | A-9 aceptado |

**Supuestos aceptados sin cambios** (sesión 2026-09-07): A-2 fuentes por status; A-6 signos del payload (`outflows` negativo, ej. JSON HSpec); A-8 granularidades `daily/weekly/monthly` (default `monthly`); A-10 coexistencia con `cash-flow-projection` sin tocarla; A-11 `credits` excluido; A-12 AR vencida fuera de ventana no aparece en la serie (extensión `include_overdue`); A-13 semántica del `summary`; A-14 filtro estricto `CASH`.

## 1. Objetivo del Proceso (*Process Objective*)

Dotar al `BudgetEngine` del método `get_cash_flow()` que produce una **serie de tiempo de liquidez** para un rango `[date_from, date_to]` con granularidad configurable: buckets históricos desde la caja real (`payment_ledger` CASH) y buckets futuros proyectados desde recaudos pendientes (`accounts_receivable`) y salidas comprometidas (presupuesto de gastos + deudas con proveedores, según `outflow_source`/`overdue_as`). El payload alimenta directo la curva de liquidez del frontend (Pilar 2), separando `actual` de `projected` en el punto del corte (D-3). El motor **no escribe ni almacena resultados**.

**Fuera de alcance**: deduplicación automática presupuesto vs. AP (regla de negocio pendiente, §13); simulación `variable_rate` (vive en el legado `project_cash_flow`, §8.4); multi-banco (el ledger no tiene dimensión de cuenta bancaria: una sola caja consolidada); conciliación bancaria formal; ingreso presupuestado como fuente de entradas (`budget_lines` income no entra: las entradas futuras son cartera `AR`, decisión del HSpec §2); P&L multi-moneda; frontend; corte por `id_cost_center` (la curva de liquidez es global; el filtro es extensión documentada).

## 2. Glosario

| Término | Definición |
| :--- | :--- |
| **Caja (*cash*)** | Dinero físico del banco: solo movimientos `transaction_nature='CASH'` del ledger SIIGO. Ajustes no-caja quedan fuera aunque muevan el saldo contable. |
| **Bucket** | Ventana de tiempo de la serie (día / semana ISO / mes calendario) con label = su fecha de inicio real. |
| **Cobertura** | Intersección del bucket con la ventana pedida `[date_from, date_to]`; los bordes parciales se recortan a la cobertura. |
| **Corte (*cutoff*)** | Fecha del punto de inflexión actual/projected. Default `date.today()`; configurable as-of con `cutoff_date` (D-3). |
| **Actual vs projected** | Status del bucket según su `end` vs. el corte (BR-24). Un bucket cruzado es `projected` y contiene solo real. |
| **Deuda vencida** | Obligación `accounts_payable.balance > 0` con `due_date < cutoff`. Su ubicación en la serie la gobierna `overdue_as` (D-2). |
| **Base ledger-relativa** | Saldo inicial derivado de la historia del ledger (no es el saldo real del banco: captura incompleta o movimientos fuera de Recibos.xlsx lo sesgan). |
| **Solape de salidas** | `(id_cost_center, bucket)` donde `budget` y `ap` proyectan simultáneamente con `outflow_source=both` (D-1); se denuncia, no se deduplica. |
| **Favorability** | No aplica: en liquidez no hay signo de "mejora"; el signo de cada componente es aritmético (BR-23). |

## 3. Arquitectura y Puntos de Integración

### 3.1 Diagrama de flujo

```text
 GET /budget/analytics/cash-flow?date_from&date_to[&granularity&id_budget&initial_balance
                                 &outflow_source&overdue_as&cutoff_date]
        |  app/api/budget/analytics.py  (router ya montado, prefix /budget/analytics)
        |  valida: fechas (E-CF-1), FK id_budget (E-CF-2), enums Literal (E-CF-3 nativo)
        |  Depends(get_current_user)
        v
 BudgetEngine.get_cash_flow() ..................... app/services/budgetEngine.py (puro-aditivo)
   Paso 0  Q0  Resolver presupuesto (D-7)                                    [1 query]
   Paso 1  _cash_buckets() -> lista (label, start, end) en Python (D-6)      [0 queries]
   Paso 2  Q1  Real: payment_ledger CASH, SUM por (dia, cash_flow)           [1 query]
           Q2  Saldo inicial: SUM abs(signo) del ledger < date_from (D-4)    [1 query*]
           Q3  AR proyectado: balance>0, due_date en [max(date_from,cutoff), date_to]  [1 query]
           Q4  AP: balance>0 + ancla segun overdue_as (D-2)                  [1 query]
           Q5  Presupuesto expense: coalesce(payment_date,budget_date)       [1 query]
           (* Q2 se omite cuando initial_balance llega)
   Paso 3  Ensamblar puntos: status (D-3), net=in+out, accumulated running
   Paso 4  summary + meta (filters, overdue_outflows, warnings de solape D-1)
   ** sin commit ** (100 % read-only, BR-32)
        v
 CashFlowResponse { summary, time_series[ {period,status,inflows,outflows,net_flow,
                                           accumulated_balance} ], meta }
```

### 3.2 Archivos modificados (cero nuevos — no aplica el checklist de 4 puntos: no hay entidad nueva)

| # | Archivo | Acción | Detalle |
| :-- | :--- | :--- | :--- |
| 1 | `app/schemas/budget/budget.py` | MOD | Bloque `CashFlow*` nuevo (§4.3) al final, junto a `PnL*` de 02_09. |
| 2 | `app/schemas/budget/__init__.py` | MOD | + imports explícitos (no `*`): `CashFlowResponse, CashFlowMeta, CashFlowSummary, CashFlowPoint`. |
| 3 | `app/schemas/__init__.py` | MOD | Extender la tupla `from .budget import (...)` con los 4 nombres. |
| 4 | `app/services/budgetEngine.py` | MOD | + `_cash_buckets()` + `get_cash_flow()` (§5), **puro-aditivo**. **No tocar** `project_cash_flow` (AC-14) ni `get_pnl` (AC-14). |
| 5 | `app/api/budget/analytics.py` | MOD | + ruta `GET /cash-flow` con `Literal` de params (§6.1) y `CashFlowResponse` en los imports. |

No se tocan: `app/main.py`, `app/api/__init__.py`, ningún modelo, ningún CRUD, ninguna tabla ⇒ **cero DDL, cero migración** (a diferencia de 02_09, que añadió `line_cost_rates`).

## 4. Estructura de Datos

### 4.1 Sin tablas nuevas — verificación del esquema vigente

Las cinco tablas fuente existen desde Sprints previos (02_07 ledger, 02_08 AR, `accounts_payable/payable_ledger` ya modeladas, `budget_lines` del módulo presupuesto). Verificación 2026-09-07 sobre BD dev: `payment_ledger` 419 filas (2022-01-01..2026-03-31; CASH in +508.861.452 / CASH out −367.856.681,92 / NON_CASH 222 filas con `cash_flow` NULL); `accounts_receivable`, `accounts_payable`, `payable_ledger`, `credits` en 0 filas (ETLs 02_07/02_08 listos; el seed de gerencia y las cargas SIIGO son prerrequisito operativo, §13).

### 4.2 Campos-fonte verificados (verdad de campo por componente)

| Componente | Tabla | Campo valor | Fecha ancla | Reglas |
| :--- | :--- | :--- | :--- | :--- |
| Entradas reales | `payment_ledger` | `payment_amount` (Numeric 15,2) | `payment_date` | `nature='CASH'` ∧ `cash_flow='in'`; aporte `+abs(amount)` (BR-23) |
| Salidas reales | `payment_ledger` | `payment_amount` | `payment_date` | `nature='CASH'` ∧ `cash_flow='out'`; aporte `-abs(amount)` (verificado: ya almacenadas negativas) |
| Entradas proyectadas | `accounts_receivable` | `balance` (Float; alias HSpec `outstanding_balance`) | `due_date` | `balance > 0`; ancla ∈ `[max(date_from,cutoff), date_to]` (BR-26) |
| Salidas proyectadas (deuda) | `accounts_payable` | `balance` (Float; neto por el CRUD de `payable_ledger`) | `due_date` | `balance > 0`; ancla por modo `overdue_as` (BR-28) |
| Salidas proyectadas (plan) | `budget_lines` (`line_type='expense'`) | `projected_amount` | `coalesce(payment_date, budget_date)` | presupuesto resuelto (D-7); ancla ∈ `[max(date_from,cutoff), date_to]` (BR-27) |
| Saldo inicial | parámetro o `payment_ledger` | Σ CASH con `payment_date < date_from` | — | D-4 |

**No usar** (trampas confirmadas en código/datos): `credits` (sin vencimiento; D-6); `payable_ledger.amount_paid` (ya descontada de `accounts_payable.balance` por el CRUD — restar de nuevo = doble conteo); `accounts_payable.status` / `accounts_receivable.status` (el CRUD de pagos escribe `'paid'/'partial'` minúsculos inválidos para el Enum ⇒ no gobernable; filtrar solo por `balance > 0`); `transaction_nature='NON_CASH_ADJUSTMENT'` (222 filas; A-14); `actual_costs`/`actual_expenses` (devengo del Pilar 1, no caja); `TAX_RATE` (D-5); `variable_rate` (mecánica de simulación del legado, BR-27); `budget_lines` `line_type='income'` (§1 fuera de alcance).

### 4.3 Schemas Pydantic (adición a `app/schemas/budget/budget.py`)

```python
class CashFlowPoint(BaseModel):
    period: str                        # label ISO del bucket (BR-34; puede ser anterior a
                                       # date_from en el primer bucket semanal parcial)
    status: str                        # "actual" | "projected" (D-3/BR-24)
    inflows: float                     # >= 0
    outflows: float                    # <= 0 (convencion del JSON de ejemplo del HSpec)
    net_flow: float                    # = inflows + outflows (nunca se "resta el negativo")
    accumulated_balance: float         # running-sum desde starting_balance (BR-35)


class CashFlowSummary(BaseModel):
    starting_balance: float
    ending_balance: float              # = starting + SUM(net_flow)  (invariante BR-35)
    net_flow: float                    # suma de net_flow de toda la ventana


class CashFlowMeta(BaseModel):
    granularity: str
    cutoff: str                        # fecha del punto de inflexion realmente usada (BR-37)
    initial_balance_source: str        # "provided" | "derived_from_ledger" (D-4)
    outflow_source: str                # eco efectivo (D-1)
    overdue_as: str                    # eco efectivo (D-2)
    budget_source: Optional[dict] = None   # {id_budget, budget_name, status} | null (D-7)
    overdue_outflows: float = 0.0      # total AP clampado/excluido segun modo
    filters: dict                      # eco de los query params efectivos (BR-39)
    warnings: List[str] = []


class CashFlowResponse(BaseModel):
    summary: CashFlowSummary
    time_series: List[CashFlowPoint]
    meta: CashFlowMeta
```

> El top-level es **exactamente** el contrato del HSpec §5 (`summary` + `time_series`) más `meta` aditivo (misma política de gobernanza que `PnLMeta` en 02_09: `outstanding` nunca silencioso: todo clamp, solape o ausencia de presupuesto se denuncia). Colisión de nombres verificada: el schema legado se llama `CashFlowProjection` y queda intacto.

## 5. Especificación Funcional — `BudgetEngine.get_cash_flow()`

### 5.1 Firma

```python
def get_cash_flow(
    self,
    date_from: date,
    date_to: date,
    granularity: str = "monthly",              # daily | weekly | monthly (BR-34)
    id_budget: Optional[int] = None,           # D-7 (misma semantica que get_pnl)
    initial_balance: Optional[float] = None,   # D-4 (parameter manda)
    outflow_source: str = "both",              # budget | ap | both (D-1)
    overdue_as: str = "clamp_cutoff",          # clamp_cutoff | first_bucket | exclude (D-2)
    cutoff_date: Optional[date] = None,        # as-of; default date.today() (D-3)
) -> Dict[str, Any]:
```

#### 5.1.1 Imports a adicionar en `budgetEngine.py`

```python
from datetime import date, timedelta     # timedelta nuevo
from sqlalchemy import case              # case nuevo (normalizacion de signos Q1/Q2)
# Los modelos PaymentLedgerModel / AccountReceivableModel / AccountPayableModel YA
# estan importados en el bloque superior del archivo (verificado lineas 43-46):
# get_cash_flow no requiere ningun import de modelos nuevo.
```

### 5.2 Generación de buckets (D-6/BR-33/BR-34 — helper privado, Python puro)

```python
def _cash_buckets(self, date_from: date, date_to: date,
                  granularity: str) -> List[tuple]:
    """Regresa [(label_iso, coverage_start, coverage_end)] cubriendo la ventana.

    weekly = lunes ISO; label = inicio REAL del bucket de calendario (puede ser
    anterior a date_from cuando la ventana abre a mitad de semana/mes, BR-34);
    la cobertura se recorta a [date_from, date_to]. Cero-fill garantizado: no
    se consulta generate_series; los buckets sin movimientos existen igual."""
    buckets: List[tuple] = []
    if granularity == "daily":
        d = date_from
        while d <= date_to:
            buckets.append((d.isoformat(), d, d))
            d += timedelta(days=1)
    elif granularity == "weekly":
        monday = date_from - timedelta(days=date_from.weekday())
        while monday <= date_to:
            sunday = monday + timedelta(days=6)
            buckets.append((monday.isoformat(),
                            max(monday, date_from), min(sunday, date_to)))
            monday += timedelta(days=7)
    else:  # monthly
        y, m = date_from.year, date_from.month
        while (y, m) <= (date_to.year, date_to.month):
            start = date(y, m, 1)
            nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            buckets.append((start.isoformat(),
                            max(start, date_from),
                            min(nxt - timedelta(days=1), date_to)))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return buckets
```

### 5.3 Paso 0 y corte

```python
cutoff = cutoff_date or date.today()
slice_lo = max(date_from, cutoff)      # piso de anclas proyectadas (BR-26/27)
warnings: List[str] = []
```

**Q0 — Resolver presupuesto**: idéntico a `get_pnl` (D-7 reutiliza 02_09 D-3): `id_budget` explícito manda (escenario ⇒ warning `"Comparing against scenario budget"`, literal compartido); default `budget_year == year(date_to) ∧ active ∧ ¬is_scenario`, menor `id_budget`, warning `"More than one active..."` si aplica; **sin presupuesto aplicable ⇒ warning `"No active non-scenario budget for {year}"` (literal compartido) y las salidas de Q5 valen 0.0** (no null: en liquidez la ausencia de plan es cero real, D-7).

### 5.4 Queries exactas (SQLAlchemy legacy `db.query`, estilo del proyecto)

**Q1 — Movimientos reales en la ventana** (agrupados por día; BR-22/BR-23):

```python
_signed = case(
    (PaymentLedgerModel.cash_flow == "in", func.abs(PaymentLedgerModel.payment_amount)),
    (PaymentLedgerModel.cash_flow == "out", -func.abs(PaymentLedgerModel.payment_amount)),
)
real_rows = (self.db.query(
        PaymentLedgerModel.payment_date,
        func.coalesce(func.sum(case(
            (PaymentLedgerModel.cash_flow == "in",
             func.abs(PaymentLedgerModel.payment_amount)), else_=0.0)), 0.0),
        func.coalesce(func.sum(case(
            (PaymentLedgerModel.cash_flow == "out",
             func.abs(PaymentLedgerModel.payment_amount)), else_=0.0)), 0.0))
     .filter(PaymentLedgerModel.transaction_nature == "CASH",
             PaymentLedgerModel.cash_flow.in_(("in", "out")),   # excluye NULL (BR-22)
             PaymentLedgerModel.payment_date >= date_from,
             PaymentLedgerModel.payment_date <= date_to)
     .group_by(PaymentLedgerModel.payment_date)
     .all())
# -> dict {date: (inflows, outflows_abs)}; cada monto entra en su bucket por cobertura
# (BR-25: una fila real con fecha futura, si existiera, cuenta como real igual — el
#  ETL carga historico; no se "anula" contra proyecciones del mismo dia: ver D-3,
#  las proyecciones se anclan a >= cutoff y el bucket cruzado es projected-only-real)
```

**Q2 — Saldo inicial derivado** (solo si `initial_balance is None`, D-4/BR-30):

```python
starting = float(self.db.query(
    func.coalesce(func.sum(_signed), 0.0)
).filter(
    PaymentLedgerModel.transaction_nature == "CASH",
    PaymentLedgerModel.cash_flow.in_(("in", "out")),
    PaymentLedgerModel.payment_date < date_from,
).scalar())
initial_balance_source = "derived_from_ledger"
warnings.append("starting_balance is ledger-relative: set initial_balance "
                "for the true bank position")
```

**Q3 — AR proyectado** (BR-26; `balance` ya es neto por el settle del CRUD 02_08):

```python
ar_rows = (self.db.query(
        AccountReceivableModel.due_date,
        func.sum(AccountReceivableModel.balance))
     .filter(AccountReceivableModel.balance > 0,        # saldo deudor (A-6 del HSpec)
             AccountReceivableModel.due_date >= slice_lo,
             AccountReceivableModel.due_date <= date_to)
     .group_by(AccountReceivableModel.due_date)
     .all())
```

**Q4 — AP con ancla `overdue_as`** (BR-28; D-2):

```python
ap_rows = (self.db.query(
        AccountPayableModel.id_cost_center,
        AccountPayableModel.due_date,
        AccountPayableModel.balance)
     .filter(AccountPayableModel.balance > 0)          # nunca filtrar por status (§13)
     .all())
overdue_outflows = 0.0
ap_anchored: List[tuple] = []       # (anchor_date, id_cost_center, amount)
for cc, due, bal in ap_rows:
    if due >= cutoff:
        anchor = due
    elif overdue_as == "clamp_cutoff":
        anchor = cutoff
        overdue_outflows += float(bal)
    elif overdue_as == "first_bucket":
        anchor = date_from
        overdue_outflows += float(bal)
    else:                            # exclude
        overdue_outflows += float(bal)   # se reporta el monto excluido igual
        continue
    if date_from <= anchor <= date_to:
        ap_anchored.append((anchor, cc, float(bal)))
if overdue_as == "exclude" and overdue_outflows:
    warnings.append(f"{n_excluded} past-due payable obligation(s) excluded "
                    "(overdue_as=exclude)")
```

**Q5 — Presupuesto de gastos** (solo si `outflow_source in ("budget","both")` y presupuesto resuelto; BR-27):

```python
bud_rows = (self.db.query(
        BudgetLineModel.id_cost_center,
        func.coalesce(BudgetLineModel.payment_date,
                      BudgetLineModel.budget_date).label("anchor"),
        func.sum(BudgetLineModel.projected_amount))
     .filter(BudgetLineModel.id_budget == resolved_id,
             BudgetLineModel.line_type == "expense",
             func.coalesce(BudgetLineModel.payment_date,
                           BudgetLineModel.budget_date) >= slice_lo,
             func.coalesce(BudgetLineModel.payment_date,
                           BudgetLineModel.budget_date) <= date_to)
     .group_by(BudgetLineModel.id_cost_center, "anchor")
     .all())
```

Reglas de invocación por `outflow_source` (D-1): `budget` ⇒ Q5 sí, Q4 no; `ap` ⇒ Q4 sí, Q5 no; `both` ⇒ ambas + detección de solape (§5.6). Las entradas proyectadas (Q3) **no** dependen de `outflow_source`.

### 5.5 Ensamblado de la serie (pseudocódigo exacto)

```python
points, accumulated = [], round(float(starting_balance_or_param), 2)
for label, b_start, b_end in buckets:
    inflow  =  Σ reales(b_start..b_end, in)  +  Σ AR con ancla en [b_start, b_end]
    outflow =  Σ reales(b_start..b_end, out) +  Σ AP + Σ Q5 en [b_start, b_end]
    status = "actual" if b_end < cutoff else "projected"       # BR-24
    net = round(inflow - outflow, 2)                           # magnitudes abs; BR-23
    accumulated = round(accumulated + net, 2)
    points.append({
        "period": label, "status": status,
        "inflows": round(inflow, 2),
        "outflows": -round(outflow, 2),     # payload SIEMPRE negativo (A-6)
        "net_flow": net,
        "accumulated_balance": accumulated,
    })
summary = {"starting_balance": points-antes-de-la-serie,
           "ending_balance": accumulated,
           "net_flow": round(ending - starting, 2)}            # BR-35/BR-37
```

### 5.6 Detección de solape (solo `outflow_source=both`, D-1/BR-29)

Encuadrar las filas de Q4 y Q5 a su bucket (`label`). Para cada `(id_cost_center, label)` presente en **ambos** lados, emitir:

```python
warnings.append(
    f"Potential outflow overlap (cost center {cc} in {label}): budget expense "
    f"{budget_total:.2f} and payable obligation {ap_total:.2f} may double-count"
)
```

Orden de warnings en el payload: selección de presupuesto → origen del saldo inicial → exclusiones `overdue_as` → solapes (estable para la UI).

### 5.7 Transaccionalidad

`get_cash_flow` es 100 % lectura (`SELECT`s; ningún `add/flush/commit/delete/update`, BR-32). 5–6 consultas por petición (Q2 se omite con `initial_balance`), sin window functions (Respuesta a la Acción-3 del HSpec: cero-fill en Python, D-6). Read Committed aceptable: serie analítica (mismo criterio BR-19 de 02_09).

## 6. Contratos de API

### 6.1 `GET /budget/analytics/cash-flow`

```python
from typing import Literal      # nuevo import en analytics.py

@router.get("/cash-flow", response_model=CashFlowResponse)
def get_cash_flow(
    date_from: date = Query(..., description="Ventana de la serie (inclusive)"),
    date_to: date = Query(..., description="Ventana de la serie (inclusive)"),
    granularity: Literal["daily", "weekly", "monthly"] = Query("monthly"),
    id_budget: Optional[int] = Query(None, description="Presupuesto para salidas (D-7; permite escenarios)"),
    initial_balance: Optional[float] = Query(None, description="Saldo real de banco antes de date_from; default: derivado del ledger (D-4)"),
    outflow_source: Literal["budget", "ap", "both"] = Query("both", description="Fuente de salidas proyectadas (D-1)"),
    overdue_as: Literal["clamp_cutoff", "first_bucket", "exclude"] = Query("clamp_cutoff", description="Ubicacion de deuda AP vencida (D-2)"),
    cutoff_date: Optional[date] = Query(None, description="As-of del punto de inflexion; default hoy (D-3)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pilar 2 - Curva de liquidez: caja real vs proyeccion AR/AP/presupuesto."""
    if date_from > date_to:
        raise HTTPException(status_code=400,
                            detail="date_from must be on or before date_to")   # literal compartido con E-1 de 02_09
    if id_budget is not None and crud.get_budget_by_id(db, id_budget) is None:
        Exceptions.register_not_found("Budget", id_budget)
    try:
        engine = BudgetEngine(db)
        return engine.get_cash_flow(
            date_from=date_from, date_to=date_to, granularity=granularity,
            id_budget=id_budget, initial_balance=initial_balance,
            outflow_source=outflow_source, overdue_as=overdue_as,
            cutoff_date=cutoff_date,
        )
    except HTTPException:
        raise
    except Exception as e:                                # patron analitica, E-CF-5
        raise HTTPException(500, detail=f"Error computing cash flow: {e}")
```

> Los `Literal` hacen redundante la validación manual de enums: FastAPI/Pydantic devuelve 422 nativo (E-CF-3).

### 6.1.1 Respuesta 200 — ejemplo canónico (golden seed §11)

Petición: `?date_from=2026-08-16&date_to=2026-10-15&granularity=monthly&initial_balance=10000000&cutoff_date=2026-09-15` (defaults `outflow_source=both`, `overdue_as=clamp_cutoff`):

```json
{
  "summary": { "starting_balance": 10000000.0, "ending_balance": 14000000.0, "net_flow": 4000000.0 },
  "time_series": [
    { "period": "2026-08-01", "status": "actual",    "inflows": 0.0,        "outflows": -0.0,        "net_flow": 0.0,        "accumulated_balance": 10000000.0 },
    { "period": "2026-09-01", "status": "projected", "inflows": 10000000.0, "outflows": -9000000.0,  "net_flow": 1000000.0,  "accumulated_balance": 11000000.0 },
    { "period": "2026-10-01", "status": "projected", "inflows": 3000000.0,  "outflows": -0.0,        "net_flow": 3000000.0,  "accumulated_balance": 14000000.0 }
  ],
  "meta": {
    "granularity": "monthly",
    "cutoff": "2026-09-15",
    "initial_balance_source": "provided",
    "outflow_source": "both",
    "overdue_as": "clamp_cutoff",
    "budget_source": { "id_budget": 1, "budget_name": "CFK Presupuesto Caja", "status": "active" },
    "overdue_outflows": 1500000.0,
    "filters": { "date_from": "2026-08-16", "date_to": "2026-10-15", "granularity": "monthly",
                 "id_budget": null, "initial_balance": 10000000.0, "outflow_source": "both",
                 "overdue_as": "clamp_cutoff", "cutoff_date": "2026-09-15" },
    "warnings": [
      "Potential outflow overlap (cost center 1 in 2026-09-01): budget expense 3000000.00 and payable obligation 5500000.00 may double-count"
    ]
  }
}
```

Trazas del golden: sept `in` = 2.000.000 real + 8.000.000 AR(due 09-23); sept `out` = 500.000 real + 1.500.000 AP vencida clampada a 09-15 + 4.000.000 AP (due 09-30) + 1.000.000 + 2.000.000 presupuesto ⇒ 9.000.000. Quedan **fuera** por contrato: 6.000.000 AR con due 07-15 (vencida, A-12), −1.000.000 AR (saldos no deudores), 9.999.999 NON_CASH (A-14). El bucket parcial agosto arranca el 08-16 pero su label es `2026-08-01` (BR-34).

### 6.1.2 Tabla de modos sobre el mismo seed (invariantes de AC-3/AC-4)

| Petición (desde el golden) | ending_balance | overdue_outflows | warnings |
| :--- | ---: | ---: | :--- |
| default (`both`+`clamp_cutoff`) | 14.000.000 | 1.500.000 | solape sept |
| `outflow_source=budget` (sin AP) | 19.500.000 | 0.0 | solape no aplica |
| `outflow_source=ap` (sin presupuesto) | 17.000.000 | 1.500.000 | solape no aplica |
| `overdue_as=first_bucket` | 14.000.000 (agosto absorbe −1.5M) | 1.500.000 | solape sept |
| `overdue_as=exclude` | 15.500.000 | 1.500.000 (excluido) | exclusion + solape |
| sin presupuesto active (D-7) | 17.000.000 | 1.500.000 | "No active non-scenario budget for 2026" (solape desaparece: no hay filas Q5) |

### 6.1.3 Diccionario de `meta`

| Campo | Regla |
| :--- | :--- |
| `cutoff` | Eco de la fecha realmente usada (parámetro o `date.today()` del servidor, BR-37). |
| `initial_balance_source` | `"provided"` si llegó el parámetro; `"derived_from_ledger"` con warning de base relativa (D-4). |
| `outflow_source` / `overdue_as` | Eco efectivo de los parámetros (default materializado). |
| `budget_source` | `{id_budget, budget_name, status}` del presupuesto de salidas; `null` si no hay (D-7; en ese caso Q5=0.0, no null). |
| `overdue_outflows` | Total AP `balance>0` con `due_date < cutoff` clampado (clamp/first_bucket) o descartado (exclude). |
| `filters` | Eco de los 8 query params con defaults efectivos (incluidos los `null`), como `meta.filters` de 02_09. |
| `warnings` | Literales de: selección de presupuesto (compartidos con 02_09), base relativa (D-4), exclusiones `overdue_as=exclude`, y solapes `(cc, bucket)` (D-1). |

## 7. Contrato CRUD

**Ninguno**: esta spec no añade entidades (a diferencia de 02_09 con `line_cost_rates`). Las cinco tablas fuente se gestiona por sus CRUDs/ETLs existentes (02_07 ledger, 02_08 AR, `accountPayable`/`payableLedger`, `budgetLines`); el motor solo lee.

## 8. Requisitos No Funcionales

### 8.1 Rendimiento y escalabilidad

- **Estrategia (Acción-3 del HSpec respondida)**: 5–6 consultas `GROUP BY + SUM` (§5.7), cero-fill en Python (D-6). Cardinalidades: ledger por día dentro de ventana (decenas–centenares de grupos), AR/AP = snapshot de cartera (cientos), presupuesto por CECO (decenas). Con 100 k filas objetivo en `payment_ledger`, latencia < 500 ms en dev Docker.
- Índices sugeridos cuando `payment_ledger` supere ~10 k filas (hoy 419; el modelo **no** indexa `payment_date` — solo `receipt_number`):

```sql
CREATE INDEX IF NOT EXISTS ix_payment_ledger_payment_date ON payment_ledger (payment_date);
CREATE INDEX IF NOT EXISTS ix_accounts_receivable_due_date ON accounts_receivable (due_date);
CREATE INDEX IF NOT EXISTS ix_accounts_payable_due_date ON accounts_payable (due_date);
```

- Sin caché v1 (requisito HSpec: curva en tiempo real). La serie semanal/mensual sobre años completos queda acotada por `date_from/date_to`; el endpoint no tiene paginación por diseño (es un gráfico).

### 8.2 Seguridad

- JWT obligatorio (coherente con `analytics.py` completo). Superficie de entrada 100 % tipada: `date`/`int`/`float`/`Literal` validados por FastAPI; SQLAlchemy parametriza; no hay interpolación de strings.
- **Gobernanza de la liquidez**: la curva bottom-line es tan sensible como el P&L; POST/PUT de tasas/presupuesto quedan restringidos al sprint de frontend (recomendación heredada de 02_09 §8.2). Los parámetros de experimentación (`outflow_source`, `overdue_as`, `cutoff_date`) son de **solo lectura** y quedan íntegros en `meta.filters` ⇒ cualquier cifra mostrada a gerencia es reproducible/auditable desde la propia petición.
- Riesgo D-1 registrado: `both` sin dedupe puede **inflar** salidas; la UI debe renderizar los warnings de solape de forma prominente (pending operativo §16-style).

### 8.3 Disponibilidad y operación

- Lecturas síncronas HTTP, sin jobs ni estado: cualquier excepción ⇒ 500 patrón (E-CF-5) sin dejar escritura a medio hacer (BR-32). Recovery de datos mal capturados: corrige el ETL/CRUD de origen y reintenta — el motor no cachea.
- Prerrequisito operativo de valor real: cargas SIIGO al día en `payment_ledger` (ETL 02_07) y snapshot de Estado de Cuenta en AR (ETL 02_08); con las tablas vacías el endpoint responde series ceros válidas (no es error).

### 8.4 Compatibilidad aguas abajo (regression surface)

- `project_cash_flow` + `GET /cash-flow-projection` **intactos** (guardia byte-a-byte, AC-14): el legado mantiene su convención `(1+TAX_RATE)`, su dedupe `(mes, CECO)` y su simulación `variable_rate`. La divergencia legado vs. Pilar 2 es **esperable y documentada**: el legado es planeación anual desde presupuesto; Pilar 2 es caja real + ventana móvil. No se unifican en v1.
- `get_pnl` (02_09) intacto: la battery smoke de Pilar 1 debe seguir pasando sin cambios (AC-14).
- Stubs `budget-vs-actual` / `tracking` intactos. Ningún consumidor actual de estas rutas en el frontend (verificado: cero matches de `cash-flow` en `crm_frontend/src`).
- Rutas nuevas sin colisión en el prefijo `/budget/analytics`.

## 9. Reglas de Negocio (numeradas, trazables; continúan la serie de 02_09)

| ID | Regla | Fuente |
| :-- | :--- | :--- |
| BR-22 | Fuente de caja real: solo `payment_ledger` con `transaction_nature='CASH'` y `cash_flow IN ('in','out')`; `NON_CASH_ADJUSTMENT` (y su `cash_flow` NULL) excluido | HSpec §2, A-14 |
| BR-23 | Normalización de signos en la fuente: `in = +abs(payment_amount)`, `out = -abs(...)`; no se confía en el signo de captura (verificado: historial `out` ya negativo). Payload: `outflows <= 0`, `net_flow = inflows + outflows` | §4.1, A-6 |
| BR-24 | Estatus por bucket: `bucket.end < cutoff ⇒ "actual"`, si no `"projected"` (el bucket que contiene el corte es projected). Bucket cruzado contiene solo real | **D-3** |
| BR-25 | Cada fila real se imputa a su `payment_date` (causación de caja), incluso si cae en bucket projected | §5.5 |
| BR-26 | Entradas proyectadas = `accounts_receivable.balance > 0` con ancla `due_date ∈ [max(date_from, cutoff), date_to]`; AR vencida antes de `date_from` no aparece (extensión `include_overdue`) | HSpec §2, A-12 |
| BR-27 | Salidas de presupuesto = `budget_lines` `line_type='expense'` del presupuesto resuelto (D-7), ancla `coalesce(payment_date, budget_date) ∈ [max(date_from,cutoff), date_to]`; todos los `behavior_type` entran sin aplicar `variable_rate` (la simulación vive en el legado) | HSpec §2, §8.4 |
| BR-28 | Deuda AP (`balance > 0`, jamás por `status`) se ancla según `overdue_as`: `clamp_cutoff` ⇒ `max(due_date, cutoff)`; `first_bucket` ⇒ `date_from`; `exclude` ⇒ solo `due_date >= cutoff`. El monto vencido afectado se publica en `meta.overdue_outflows` | **D-1/D-2** |
| BR-29 | `outflow_source` gobierna las salidas proyectadas (`budget`/`ap`/`both`, default `both`); en `both` NO se deduplica: cada `(id_cost_center, bucket)` coincidente emite warning de solape con ambos totales | **D-1** |
| BR-30 | `initial_balance` explícito manda; default derivado = Σ firmado del ledger CASH con `payment_date < date_from`, con warning de base relativa y `meta.initial_balance_source` | **D-4** |
| BR-31 | Selección de presupuesto idéntica a 02_09 D-3 (activos no-escenario de `year(date_to)`, menor id; `id_budget` manda; escenario ⇒ warning compartido). Sin presupuesto ⇒ salidas proyectadas **0.0** (no null) + warning | **D-7** |
| BR-32 | El motor no escribe: ningún `add/flush/commit/delete/update` en `get_cash_flow`/`_cash_buckets` | §5.7 |
| BR-33 | Todos los buckets de la ventana aparecen en `time_series` (cero-fill en Python; sin `generate_series`) | **D-6** |
| BR-34 | `weekly` = semanas ISO lunes–domingo; `label` = inicio real del bucket de calendario (puede ser anterior a `date_from`); cobertura recortada a la ventana; `daily`/`monthly` análogos | §5.2 |
| BR-35 | Invariante contractual: `ending_balance = starting_balance + Σ net_flow` (acumulación continua, sin saltos, sobre TODA la serie); cada `accumulated_balance` es el prefijo exacto | §5.5 |
| BR-36 | Fuentes prohibidas del contrato: `credits`, `payable_ledger` (neto ya descontado), `status` de AP/AR, `actual_costs`/`actual_expenses` (devengo), `TAX_RATE`, `budget_lines` income | Preámbulo, §4.2 |
| BR-37 | `cutoff_date` (as-of) es de solo lectura y se ecoa en `meta.cutoff` + `meta.filters`; default = `date.today()` del servidor (UTC del contenedor; documented trap §13) | **D-3** |
| BR-38 | Redondeo a 2 decimales en cada punto, summary y `overdue_outflows` | §5.5 |
| BR-39 | `meta.filters` eco exacto de los 8 params con defaults efectivos (incluidos `null`), mismo patrón de gobernanza que 02_09 | §6.1.3 |
| BR-40 | El top-level del payload respeta el contrato del HSpec §5 (`summary` + `time_series`); `meta` es aditivo no-rompente | §4.3 |

## 10. Catálogo de Errores

| # | Código | Trigger | `detail` |
| :-- | :--- | :--- | :--- |
| E-CF-1 | 400 | `date_from > date_to` | `"date_from must be on or before date_to"` (literal compartido con E-1 de 02_09) |
| E-CF-2 | 404 | `id_budget` inexistente | patrón `Exceptions.register_not_found("Budget", ...)` |
| E-CF-3 | 422 | `granularity`/`outflow_source`/`overdue_as` fuera de enum, o fechas mal formateadas | nativo FastAPI (`Literal`/`date`) |
| E-CF-4 | 401/403 | Sin JWT | estándar FastAPI |
| E-CF-5 | 500 | Cualquier otra excepción BD/parseo | `"Error computing cash flow: {e}"` (patrón analítica) |

Sin presupuesto, sin datos en la ventana, o ventana 100 % pasada/futura **no son errores**: 200 con series ceros y warnings (misma filosofía E-6 de 02_09).

## 11. Criterios de Aceptación (golden seed determinístico)

**Seed de prueba** (BD dev con backend :8003; marcador `CFK` para idempotencia, patrón del smoke 02_09; el corte falso `cutoff_date=2026-09-15` hace toda la batería determinística):

- CECO `CFK-A` (sin línea). Presupuesto `CFK Presupuesto Caja` (`active`, `is_scenario=False`, `budget_year=2026`) con gastos: 2026-09-20 por 1.000.000 y 2026-09-30 por 2.000.000 (ambos en CFK-A, `behavior_type` fijo).
- `payment_ledger` (todos `CASH`, `receipt_number LIKE 'CFK%'`): 2026-07-01 `in` +5.000.000 y 2026-07-20 `out` −1.200.000 (precarga del saldo derivado); 2026-09-05 `in` +2.000.000; 2026-09-12 `out` +500.000 capturada **con signo invertido a propósito** (BR-23); 2026-09-08 naturaleza `NON_CASH_ADJUSTMENT` +9.999.999 (debe excluirse).
- `accounts_receivable` (`document_number LIKE 'CFK%'`): due 2026-09-23 balance 8.000.000; due 2026-10-05 balance 3.000.000; due 2026-09-25 balance −1.000.000 (no deudora); due 2026-07-15 balance 6.000.000 (vencida fuera de ventana).
- `accounts_payable`: CFK-A due 2026-09-03 balance 1.500.000 (vencida al corte falso); due 2026-09-30 balance 4.000.000.
- Cuarentena temporal (restore en `finally`, herencia del smoke 02_09): otros presupuestos `active` no-escenario de 2026.

Ventana golden: `date_from=2026-08-16`, `date_to=2026-10-15`.

| AC | Criterio |
| :-- | :--- |
| **AC-1** (integración) | Cero DDL: `GET /budget/analytics/cash-flow` responde 200 con JWT; `from app.schemas import CashFlowResponse` importa; OpenAPI lista la ruta con `$ref CashFlowResponse` y los 4 schemas `CashFlow*` en components (Swagger UI en `/`, patrón I-6 de 02_09). |
| **AC-2** (golden) | La petición de §6.1.1 reproduce **exactamente** el JSON de §6.1.1: 3 buckets (agosto `actual` ceros con label `2026-08-01` — BR-34; sept `projected` 10M/−9M/+1M/11M; oct 3M/0/+3M/14M), summary 10M/14M/+4M, `overdue_outflows` 1.500.000 y el warning de solape literal con totales 3.000.000/5.500.000. Verificación SQL cruzada ±0.01 de cada escalar (§12.2). |
| **AC-3** (D-1) | Modos de `outflow_source` sobre el mismo seed: `budget` ⇒ ending 19.500.000; `ap` ⇒ 17.000.000; `both` ⇒ 14.000.000; el warning de solape **solo** aparece en `both`. |
| **AC-4** (D-2) | Modos de `overdue_as`: `clamp_cutoff` ⇒ deuda 1.5M cae en sept y `overdue_outflows` 1.5M; `first_bucket` ⇒ cae en agosto (net −1.5M, accumulated 8.5M) con **ending idéntico** al clamp (14M, invariante de ventana); `exclude` ⇒ ending 15.5M + warning de exclusión con el monto. |
| **AC-5** (D-4) | Sin `initial_balance`: `starting_balance == SELECT Σ firmado CASH < 2026-08-16` (cross-check SQL, **no** literal — la base dev tiene historia SIIGO) y `initial_balance_source="derived_from_ledger"` + warning literal de base relativa; con parámetro ⇒ `"provided"` y sin warning. |
| **AC-6** (BR-23) | La fila `out` sembrada como +500.000 aparece en el payload como −500.000 (sept `outflows` exacto −9.000.000): normalización `abs()` demostrada con dato adverso. |
| **AC-7** (BR-22/A-14) | La fila `NON_CASH_ADJUSTMENT` de +9.999.999 no afecta bucket, saldo derivado ni summary (asserts de valores exactos del golden). |
| **AC-8** (BR-26/A-12) | AR de 6.000.000 (due 2026-07-15) y la de −1.000.000 no aparecen en ningún bucket; `inflows` de la serie = 2M+8M+3M exactos. |
| **AC-9** (D-3/BR-24) | Con `cutoff_date=2026-09-15` y `granularity=daily`: bucket `2026-09-14` ⇒ `actual`, `2026-09-15` ⇒ `projected`; con la ventana mensual, agosto (end 08-31 < 09-15) ⇒ `actual`. |
| **AC-10** (BR-33/34) | Counts de serie sobre la ventana: `daily` ⇒ 61 puntos; `weekly` ⇒ 10 buckets, primer label `2026-08-10` (< date_from, BR-34); `monthly` ⇒ 3. Todos los buckets presentes aunque ceros (cero-fill). |
| **AC-11** (BR-35) | En TODAS las respuestas capturadas (batería completa): `ending == starting + Σ net` y la secuencia `accumulated_balance` es prefijo continuo desde `starting`. |
| **AC-12** (D-7) | Archivar el presupuesto CFK ⇒ 200, salidas de presupuesto 0.0 (agosto/sept sin Q5: sept outflows −6.000.000 = 0.5+1.5+4.0), `budget_source` null, warning `"No active non-scenario budget for 2026"`, y **sin** warning de solape; restaurar. Con `id_budget=clon` escenario ⇒ warning `"Comparing against scenario budget"` (literales compartidos con 02_09 verifican consistencia). |
| **AC-13** (BR-32) | Conteos idénticos antes/después de 5 llamadas en `payment_ledger`, `accounts_receivable`, `accounts_payable`, `payable_ledger`, `budget_lines`, `budgets`. |
| **AC-14** (regresión) | `cash-flow-projection?budget_year=2026` byte-a-byte igual antes/después de toda la batería; stubs `budget-vs-actual`/`tracking` intactos; y el smoke de 02_09 (`test_pnl_engine_smoke.py`) sigue 208/208 (get_pnl no tocado). |
| **AC-15** (errores) | E-CF-1 400 con literal exacto; E-CF-3 422 con `granularity=quarterly`, `outflow_source=mixed`, `overdue_as=clamp` (mal escrito), `cutoff_date` inválida; E-CF-2 404 `id_budget=999999`; E-CF-4 401/403 sin token. |
| **AC-16** (idempotencia) | Post-ejecución: cero filas `CFK%` en las 6 tablas, conteos == snapshot inicial, cuarentenas restauradas (mismo estándar del smoke SMK de 02_09). |

## 12. Estrategia de Pruebas (el proyecto sigue sin test suite; se extiende el patrón de 02_09)

1. **Smoke script dedicado**: `crm_backend/test/test_cash_flow_engine_smoke.py`, clonando la arquitectura del de P&L: fase 0 pre-clean `CFK%`, login JWT, seed SQL directo (MAX+1, lección de secuencias desincronizadas del ETL dev), cuarentena de presupuestos ajenos de 2026 con restore en `finally`, marcador de checks y reporte `N/M`.
2. **Determinismo por `cutoff_date`**: la batería usa SIEMPRE el corte falso 2026-09-15; un check adicional opcional ejecuta la petición **sin** `cutoff_date` y verifica `meta.cutoff == date.today()` del servidor (bridge AC de D-3, tolerante a calendario).
3. **Verificación SQL cruzada** (patrón §12.2 de 02_09): para cada escalar del golden, la consulta de la misma fuente con los mismos WHERE debe coincidir ±0.01 (ledger firmado, AR deudor, AP balance, presupuesto coalesce).
4. **Matriz de modos**: AC-3/AC-4 combinando `outflow_source × overdue_as` (6 combinaciones sobre el mismo seed; el producto completo no se fija en valores literales salvo los 6 de §6.1.2).
5. **Regresión**: AC-14 corre el smoke 02_09 completo al final (los dos pilares comparten `budgetEngine.py`; la guardia cruzada es barata y detecta colisiones de refactor).

## 13. Supuestos y Dependencias

- **Dep-BD**: Postgres 16; **cero cambios de esquema** (no aplica el checklist de 4 puntos de registro). Despliegue = deploy del código; sin orden tabla→tasas→motor.
- **Datos**: la calidad de la curva depende de la disciplina de captura SIIGO: `payment_ledger` (Recibos.xlsx, 02_07) y Estado de Cuenta (02_08) al día; AP (`accounts_payable`) se captura hoy por CRUD sin ETL dedicado — sin carga AP, los modos `ap`/`both` solo muestran presupuesto (no es error).
- **IVA (D-5)**: se asume que el presupuesto de gastos captura montos de pago con IVA. Si el negocio confirma captura neta, la corrección es **un único factor** `(1 + TAX_RATE)` en Q5 (y el contrato no cambia de forma); quedó registrado para validarse contra SIIGO en la primera operación real.
- **Solape D-1**: la no-deduplicación es consciente; una regla de match definitiva (p. ej. referencia de documento de origen en `budget_lines`, columna nueva = sprint futuro con rompe-contrato de Excel) es la única dedupe confiable. Mientras tanto: warnings visibles.
- **Timezone**: `date.today()` corre en UTC (contenedor dev/prod); el corte puede adelantarse/atrasarse hasta 5 h contra la fecha calendario de Colombia. Atenuación operativa: el frontend puede enviar `cutoff_date` con la fecha local; documentado en AC-1 check puente.
- **Bug preexistente fuera de alcance** (patrón I-7): `create_payable_ledger` asigna `'paid'/'partial'` (minúsculas) a columnas Enum cuyas etiquetas reales son `PAID/PARTIAL` ⇒ puede fallar en flush y hace `status` no confiable. El motor lo evita (BR-36); **ticket recomendado** de mantenimiento: usar `PayableStatusEnum.PAID/PARTIAL` en el CRUD.
- **Serie "de una sola caja"**: `payment_ledger` no distingue cuentas bancarias; si el negocio abre segunda cuenta, la serie mezcla cajas (extensión: columna `bank_account` nullable + filtro, no rompe el contrato actual).
- **Nomenclatura**: el HSpec sugería `GET /budget/analytics/cash-flow`; se adopta literal (hermana de `/pnl` bajo el mismo router; el legado queda como `cash-flow-projection` para no romper a nadie aunque hoy no tenga consumidores).

## 14. Matriz de Trazabilidad (HSpec → especificación)

| HSpec | Estado | Dónde |
| :--- | :--- | :--- |
| §1 Objetivo (curva de liquidez, time-series) | Aceptado | §1, §5.5, §6.1.1 |
| §2 Fuentes (ledger CASH / AR / presupuesto expense) | Aceptado con nombres reales (`balance` no `outstanding_balance`) + **AP añadida por decisión** | Preámbulo 1, §4.2, D-1 |
| §3.1 Saldo inicial | Especificado: parámetro o derivado con warning de relatividad | D-4, BR-30 |
| §3.2/3.3 Entradas/salidas históricas y futuras | Especificado con normalización de signos y anclas exactas | BR-23..BR-28 |
| §3.4/3.5 Net flow y accumulated | Especificado con invariante verificable | §5.5, BR-35, AC-11 |
| §4 Parámetros (rango, granularity, initial_balance) | Aceptado + **tres parámetros nuevos de sesión** (`outflow_source`, `overdue_as`, `cutoff_date`) | §6.1, D-1..D-3 |
| §5 Payload JSON (summary + time_series, status) | Aceptado literal + `meta` aditivo de gobernanza | §4.3, BR-40 |
| Acción-1 (punto de inflexión) | **Respondido**: cutoff=today (override as-of), buckets cruzados projected-only-real, día del corte = projected | D-3, BR-24, AC-9 |
| Acción-2 (cuentas por pagar) | **Respondido**: la tabla existe y entra; default `both` sin dedupe con warnings; `payable_ledger` excluida (balance ya neto) | Preámbulo 3, D-1/D-2, BR-28/29 |
| Acción-3 (generate_series) | **Respondido**: cero-fill en Python, serie siempre completa | D-6, BR-33, AC-10 |

## 15. Checklist de Implementación (orden recomendado)

1. [x] Schemas `CashFlow*` en `schemas/budget/budget.py` + registros en ambos `__init__.py (§3.2 #1–3).
2. [x] `BudgetEngine._cash_buckets()` + `get_cash_flow()` Q0..Q5 + ensamblado (§5, puro-aditivo; ver `git diff` muestra `project_cash_flow`/`get_pnl` sin cambios) ⇒ #4.
3. [x] Endpoint `GET /cash-flow` en `analytics.py` con Literals y validaciones E-CF-1/2 (§6.1) ⇒ #5.
4. [x] Smoke `test/test_cash_flow_engine_smoke.py` (AC-1..AC-16, §12) ⇒ cerrar verificación.
5. [x] Ejecutar además `test_pnl_engine_smoke.py` (guardia cruzada AC-14).
6. [ ] Comunicar el contrato §6.1 (payload + modos + warnings) al frontend para la curva de liquidez (etiquetas "se paga al primer momento de liquidez" para `clamp_cutoff`, banner de solapes).

---

*Fin de la especificación — v1.0 (2026-09-07): consolidada desde el HSpec Pilar 2 del stakeholder, la verificación de verdad de campo sobre el esquema y datos reales de dev (419 filas de ledger con signos adversos verificados, trampas de `status`/`payable_ledger` leídas del CRUD), y las decisiones D-1..D-7 de la sesión interactiva (A-3 rechazado → parametrización `outflow_source`/`overdue_as`). Estado: **aprobada (2026-09-07) — implementada y verificada (2026-09-07)**.*
