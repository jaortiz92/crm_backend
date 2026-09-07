# Especificación Técnica: Budget Engine — Pilar 1 (Estado de Resultados / P&L)

| Campo | Valor |
| :--- | :--- |
| **Documento** | Spec Motor Financiero — P&L (accrual) + tabla maestra de tasas de costo por línea |
| **Módulo** | `budget` → servicio `BudgetEngine.get_pnl()` + tabla nueva `line_cost_rates` + endpoint `GET /budget/analytics/pnl` |
| **Versión** | 1.2 (v1.1 erratas de implementación I-1..I-7 y §16; 2026-09-04) |
| **Fecha** | 2026-09-04 |
| **Estado** | **Aprobada (2026-09-04) e implementada** — AC-1..AC-16 verificados (86/86, schema aislado; ver §16) |
| **Origen** | HSpec Pilar 1 (stakeholder) + sesión interactiva de definición (Decisiones D-1..D-5) |
| **Patrón** | Capa de agregación de solo lectura (no persiste resultados) + 1 entidad maestra nueva con checklist de 4 puntos de registro |
| **Fuentes analizadas** | `app/models/invoice.py`, `app/models/invoiceDetail.py`, `app/models/credit.py`, `app/models/reference.py`, `app/models/brand.py`, `app/models/line.py`, `app/models/budget/*.py`, `app/services/budgetEngine.py`, `app/api/budget/analytics.py`, `app/api/budget/__init__.py`, `app/api/budget/upload.py`, `app/schemas/budget/budget.py` |

> **Correcciones frente al HSpec base** (hallazgos verificados en código + decisiones del stakeholder):
> 1. **No existe la tabla `actual_incomes`.** La facturación causada vive únicamente en `invoices` / `invoice_details`. Action-Item 1 del HSpec queda resuelto: **fuente = `invoices`** (§5.2 Q1).
> 2. **La tabla `credits` NO contiene notas de crédito**: registra cartera a plazo (`term`, `credit_value`, `payment_value`, `balance`, `paid`) y alimenta el pilar de liquidez. No puede usarse como deducción de ingresos. Resuelto por D-1: las devoluciones llegan como **facturas con valores negativos**.
> 3. **No existe plantilla de presupuesto de costos** (solo `budget-plan-income` y `budget-plan-expense` en `upload.py`). Resuelto por D-2: nueva tabla maestra `line_cost_rates` (% de COGS por línea, con vigencia).
> 4. Las facturas **no tienen dimensión de centro de costos** (ruta `invoices → orders → customer_trips`, sin FK a CECO). El filtro `id_cost_center` no aplica a ingresos (BR-9, `meta.not_filterable`).

## 0. Registro de Decisiones (Decision Log)

| ID | Decisión | Origen |
| :--- | :--- | :--- |
| **D-1** | **Devoluciones / notas de crédito = facturas con importes negativos cargadas en `invoices`** (encabezado negativo con sus `invoice_details` negativos). Ingresos Netos = `SUM(total_without_tax)` sin línea separada de devoluciones. Una factura negativa **sin** `id_reference` en sus detalles solo afecta el P&L consolidado (queda fuera de los cortes por línea/referencia por el JOIN interno, §5.2 Q1b) y se reporta en `meta.warnings` si existe `id_line`. | Supuesto 3 rechazado por stakeholder (2026-09-04) |
| **D-2** | **Presupuesto de COGS = Σ (ingreso presupuestado por centro de costos × tasa de costo vigente de la línea del CECO)**. La tasa vive en la tabla nueva `line_cost_rates` (id_line, cogs_pct, vigencia date_from/date_to, is_active). `id_line = NULL` = **tasa global de respaldo** para CECOs sin línea o sin tasa propia. Sin ninguna tasa aplicable ⇒ `cogs.budget = null` (nunca 0). | Supuesto 4 rechazado → opción 1 del árbol de alternativas |
| **D-3** | **Selección del presupuesto**: sin `id_budget` ⇒ presupuesto con `budget_year == year(date_to)`, `status = 'active'`, `is_scenario = False` (dominio de statuses `draft/active/archived` según `app/schemas/budget/budget.py`). `id_budget` explícito manda (permite comparar escenarios clonados). Sin presupuesto aplicable ⇒ respuesta 200 con `budget: null` en todas las líneas + warning. | Supuesto 5 aceptado |
| **D-4** | **Varianza con convención de favorabilidad** (positivo = favorable a la utilidad): ingresos y utilidades `actual − budget`; COGS y OPEX `budget − actual`. Coincide con el JSON de ejemplo del HSpec (−10.000 / +5.000 / −2.000). | Supuesto 8 aceptado |
| **D-5** | La tasa se define **solo por línea de producto** (`lines`), sin granularidad por temporada (`collections`). Extensión futura documentada (§13). | Implícito en D-2 |
| **D-6** | **Red de respaldo gobernable**: cadena de resolución de tasas = tasa de línea → tasa global (`id_line = NULL`) → exclusión con warning (BR-7/BR-15). El payload publica `meta.cogs_budget_trace` con la resolución CECO-por-CECO (BR-21, AC-16). Riesgo registrado: la tasa global apalanca todos los CECOs sin línea; gobernanza de gerencia en §8.2. | Revisión stakeholder punto 2 → opción 1 (2026-09-04) |

**Supuestos aceptados sin cambios** (sesión 2026-09-04): A-1 ingresos netos de IVA (`total_without_tax`, base homogénea con `budget_lines.income` que el cash-flow ya documenta como NET); A-2 los descuentos ya están incorporados en `total_without_tax` (no se resta `total_discount`); A-6/A-7 semántica de filtros por dimensión (§5.4); A-9 márgenes sobre cifras reales, 1 decimal, `null` si ingresos = 0; A-10 rango de fechas requerido e inclusivo, los cortes YTD/mensuales los decide el frontend.

## 1. Objetivo del Proceso (*Process Objective*)

Dotar al `BudgetEngine` del método `get_pnl()` que genera en tiempo real el **Estado de Resultados por causación** de la empresa para un rango de fechas, comparando **Real vs Presupuestado vs Varianza** con la estructura jerárquica Ingresos → COGS → Utilidad Bruta → OPEX → Utilidad Operativa, y exponerlo vía `GET /budget/analytics/pnl` con payload listo para graficar. El motor **no escribe ni almacena resultados**: es una capa de agregación sobre las tablas del Sprint 1.

**Fuera de alcance**: conciliación contable formal (no reemplaza la declaración de resultados del contador); IVA e impuestos de renta; P&L multi-moneda; corte de OPEX/presupuesto por referencia de producto (no existe dimensión); frontend (documento aparte); presupuesto de COGS cargado por Excel (D-2 lo resuelve con tasas).

## 2. Glosario

| Término | Definición |
| :--- | :--- |
| **Causación (*accrual*)** | El hecho económico se imputa a la fecha del documento (`invoice_date`, `cost_date`, `expense_date`, `budget_date`), no a la fecha de pago. |
| **Ingresos Netos** | `SUM(invoices.total_without_tax)` del periodo: las facturas negativas (devoluciones, D-1) ya restan dentro de la sumatoria. |
| **Tasa de costo (*COGS pct*)** | Porcentaje del ingreso que la gerencia planea como costo directo, vigente por línea de producto y periodo (§4). |
| **CECO** | Centro de costos (`cost_centers`); unidad de planeación del presupuesto. Su `id_line` permite atribuir ingreso presupuestado a línea. |
| **Modo consolidado** | Petición sin `id_line`/`id_reference`: ingresos medidos a nivel encabezado de factura (canónico, conciliable con SIIGO). |
| **Modo corte (*slice*)** | Petición con `id_line` y/o `id_reference`: ingresos medidos a nivel detalle (`SUM(value_without_tax)` de las filas coincidentes); OPEX real y presupuesto de gasto se devuelven `null`. |
| **Varianza favorable** | Desviación que suma a la utilidad (positiva). Ver D-4. |
| **Tasa global de respaldo** | Fila de `line_cost_rates` con `id_line = NULL`; se aplica a CECOs cuya línea no tiene tasa vigente. |
| **Favorability chain** | Regla de nulos: si `cogs.budget` no es calculable, `gross_profit.budget` y `operating_profit.budget` también son `null` (no se propaga un presupuesto de costo = 0). |

## 3. Arquitectura y Puntos de Integración

### 3.1 Diagrama de flujo

```text
 GET /budget/analytics/pnl?date_from&date_to[&id_budget&id_cost_center&id_line&id_reference&include_breakdown]
        |  app/api/budget/analytics.py  (router ya montado, prefix /budget/analytics)
        |  valida: fechas, FKs de filtros (404 si inexistente) -> Depends(get_current_user)
        v
 BudgetEngine.get_pnl() .............................. app/services/budgetEngine.py
   Paso 0  Q0  Resolver presupuesto (D-3)                                   [1 query]
   Paso 1  Q1  Ingresos reales   invoices[.invoice_details]                 [1 query]
           Q2  COGS real         actual_costs                               [1 query]
           Q3  OPEX real         actual_expenses (+Q3b breakdown)           [1 query]
           Q4  Ingreso presup.   budget_lines JOIN budgets JOIN cost_centers[1 query]
           Q5  Gasto presup.     idem, line_type='expense'                  [1 query]
           Q6  Tasas vigentes    line_cost_rates                            [1 query]
   Paso 2  cogs.budget = SUM_cc (ingreso_b(cc) * pct(linea_cc)/100)    (D-2)
           Q7* mapa CECO->codigo para meta.cogs_budget_trace (D-6, condicional)
   Paso 3  Derivados: gross/operating, varianzas (D-4), margenes
   Paso 4  Ensamblar payload + meta (not_filterable, warnings)
   ** sin commit ** (puremente read-only)
        v
 PnLResponse { period, pnl_statement{revenues,cogs,gross_profit,opex,operating_profit}, meta }
```

### 3.2 Archivos nuevos y modificados (checklist de registro — 4 puntos + wiring budget)

| # | Archivo | Acción | Detalle |
| :-- | :--- | :--- | :--- |
| 1 | `app/models/budget/lineCostRate.py` | **NUEVO** | Modelo §4.2. |
| 2 | `app/models/budget/__init__.py` | MOD | + `from .lineCostRate import LineCostRate` |
| 3 | `app/models/__init__.py` | MOD | Añadir `LineCostRate` a la tupla `from .budget import (...)` (línea ~34). |
| 4 | `app/schemas/budget/lineCostRate.py` | **NUEVO** | Schemas de la entidad §4.3.1 (patrón: `budgetScenario.py`). |
| 5 | `app/schemas/budget/budget.py` | MOD | + schemas `PnL*` al final del archivo, junto a `BudgetVsActual/CashFlowProjection` §4.3.2. |
| 6 | `app/schemas/budget/__init__.py` | MOD | + imports explícitos (no `*`): `LineCostRate, LineCostRateCreate, LineCostRateUpdate` y `PnLResponse, PnLMeta, PnLStatement, PnLComparison, PnLProfit, PnLOpex, OpexBreakdownItem, CogsBudgetTraceItem`. |
| 7 | `app/schemas/__init__.py` | MOD | Extender la tupla `from .budget import (...)` (línea ~49) con los nombres nuevos. |
| 8 | `app/crud/budget/lineCostRate.py` | **NUEVO** | CRUD §7 (patrón: `costCenter.py`, estilo legacy `db.query`). |
| 9 | `app/crud/budget/__init__.py` | MOD | + `from .lineCostRate import *` |
| 10 | `app/api/budget/lineCostRate.py` | **NUEVO** | CRUD REST §6.2. |
| 11 | `app/api/budget/__init__.py` | MOD | `from .lineCostRate import router as line_cost_rate_router` + `budget.include_router(line_cost_rate_router, prefix="/line-cost-rate", tags=["Line Cost Rates"])` |
| 12 | `app/services/budgetEngine.py` | MOD | + método `get_pnl()` §5 + imports nuevos (§5.1.1). **No tocar** `project_cash_flow` (regresión AC-13). |
| 13 | `app/api/budget/analytics.py` | MOD | + ruta `GET /pnl` §6.1 (debajo de las rutas existentes; requiere `from datetime import date` y `PnLResponse` en los imports de `app.schemas.budget`). |

No se tocan: `app/main.py` ni `app/api/__init__.py` (el router padre `/budget` ya incluye `analytics`); ninguna tabla existente sufre cambios de esquema ⇒ **no hay ALTER** (solo `create_all` de la tabla nueva, §4.1).

## 4. Estructura de Datos

### 4.1 Tabla nueva `line_cost_rates` — DDL de referencia

`Base.metadata.create_all` la crea en el primer arranque post-deploy (tabla nueva ⇒ sin migración manual). El DDL es spec del nombre/tipo para revisión:

```sql
CREATE TABLE line_cost_rates (
    id_line_cost_rate SERIAL PRIMARY KEY,
    id_line       INTEGER REFERENCES lines (id_line),        -- NULL = tasa global de respaldo (D-2)
    rate_name     VARCHAR(120),                              -- etiqueta libre ("COGS Deportiva 2026")
    cogs_pct      NUMERIC(5, 2) NOT NULL,                    -- 0.00-100.00 (validación Pydantic ge/le)
    date_from     DATE NOT NULL,                             -- vigencia inclusiva
    date_to       DATE NOT NULL,
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);
-- index=True del modelo: ix_line_cost_rates_id_line, ix_line_cost_rates_date_from, ix_line_cost_rates_date_to
```

**Sin `CHECK (date_to >= date_from)` ni unique**: se aplican en CRUD (§7, BR-12/13) porque el proyecto no usa constraints SQL exóticos y `create_all` los emitiría sin Alembic.

### 4.2 Modelo (`app/models/budget/lineCostRate.py`)

```python
"""
LineCostRate Model

Master catalog: budgeted COGS percentage per product line with validity
periods (Pilar 1 - P&L).  id_line = NULL defines the global fallback rate
used by cost centers whose line has no active rate.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Numeric, Date, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class LineCostRate(Base):
    """Budgeted COGS % per line, with validity period (D-2)."""
    __tablename__ = "line_cost_rates"

    id_line_cost_rate = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=True, index=True)
    rate_name = Column(String(120), nullable=True)
    cogs_pct = Column(Numeric(5, 2), nullable=False)
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    is_active = Column(Boolean, server_default="True")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    line = relationship("Line", backref="cost_rates")
```

### 4.3 Schemas Pydantic

#### 4.3.1 Schemas de la entidad (`app/schemas/budget/lineCostRate.py`)

```python
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class LineCostRateBase(BaseModel):
    id_line: Optional[int] = Field(None, description="FK lines.id_line. NULL = global fallback rate")
    rate_name: Optional[str] = Field(None, max_length=120)
    cogs_pct: float = Field(..., ge=0, le=100, description="Budgeted COGS % of revenue (0-100)")
    date_from: date
    date_to: date
    is_active: Optional[bool] = Field(True)

    model_config = ConfigDict(from_attributes=True)


class LineCostRateCreate(LineCostRateBase):
    pass


class LineCostRateUpdate(BaseModel):
    """Partial update: every field optional; validators of §7 re-run on merge."""
    id_line: Optional[int] = None
    rate_name: Optional[str] = Field(None, max_length=120)
    cogs_pct: Optional[float] = Field(None, ge=0, le=100)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    is_active: Optional[bool] = None


class LineCostRate(LineCostRateBase):
    id_line_cost_rate: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

#### 4.3.2 Payload P&L (adición a `app/schemas/budget/budget.py`)

```python
from datetime import date          # extender imports del archivo
from typing import List, Optional  # ya presentes en el archivo

class PnLComparison(BaseModel):
    actual: Optional[float] = None      # Optional: en modo corte hay lineas no filtrables (null)
    budget: Optional[float] = None      # None = sin presupuesto aplicable / no cortable
    variance: Optional[float] = None    # convencion de favorabilidad (D-4)
    variance_pct: Optional[float] = None


class PnLProfit(BaseModel):
    actual: Optional[float] = None
    budget: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    margin_pct: Optional[float] = None          # real (A-9)
    margin_pct_budget: Optional[float] = None   # presupuestado (aditivo, no rompe el contrato del HSpec)


class OpexBreakdownItem(BaseModel):
    category: str        # expense_type del libro auxiliar
    actual: float


class PnLOpex(PnLComparison):
    breakdown: Optional[List[OpexBreakdownItem]] = None   # solo con include_breakdown=true


class PnLStatement(BaseModel):
    revenues: PnLComparison
    cogs: PnLComparison
    gross_profit: PnLProfit
    opex: PnLOpex
    operating_profit: PnLProfit


class CogsBudgetTraceItem(BaseModel):
    id_cost_center: int
    cost_center_code: Optional[str] = None       # denormalizado para tooltips de UI
    id_line: Optional[int] = None                # linea del CECO (null = sin linea)
    pct: float                                   # tasa aplicada (0-100)
    source: str                                  # "line" | "global" (D-6)
    income_budget: float                         # ingreso presupuestado del CECO en el periodo
    cogs_contribution: float                     # income_budget * pct / 100 (2 dec)


class PnLMeta(BaseModel):
    mode: str                                    # "consolidated" | "slice"
    budget_source: Optional[dict] = None         # {id_budget, budget_name, status}
    filters: dict                                # eco exacto de los query params recibidos
    not_filterable: List[str] = []               # p.ej. "revenues (no cost-center dimension)"
    cogs_budget_trace: List[CogsBudgetTraceItem] = []   # D-6: auditoria CECO-por-CECO de cogs.budget
    warnings: List[str] = []                     # BR-15: tasas faltantes, ano cruzado, NC sin referencia


class PnLResponse(BaseModel):
    period: dict          # {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}  — mismo shape que el HSpec
    pnl_statement: PnLStatement
    meta: PnLMeta
```

> `period` se arma como dict con claves literales `"from"`/`"to"` (idéntico al JSON del HSpec; `from` es palabra reservada en Python, de ahi el tipo `dict` y no un BaseModel con campos directos). El motor lo construye con `{"from": date_from.isoformat(), "to": date_to.isoformat()}`.

### 4.4 Reglas de vigencia y resolución de la tasa

1. **Vigente al corte**: una tasa aplica a un P&L si `is_active = TRUE AND date_from <= date_to_query AND date_to >= date_to_query` (la vigencia toca el último día del periodo consultado). Datos corruptos con dos tasas solapadas-vigentes: gana la de mayor `id_line_cost_rate` (más reciente); nunca es error en lectura.
2. **Cadena de fallback por CECO**: `pct = tasa(linea del CECO) -> tasa global (id_line NULL) -> sin pct`. CECO sin pct ⇒ su ingreso presupuestado **se excluye** de `cogs.budget` (no se asume 0%) y se lista en `meta.warnings` (BR-15). Si ningún CECO tiene pct ⇒ `cogs.budget = null` (favorability chain, §2).
3. **Anti-solape (escritura)**: dos tasas activas de la **misma** `id_line` (o dos globales) no pueden solapar vigencia (BR-13). La comparación NULL-safe usa `.is_(None)` para el grupo global.
4. **Unidad de `cogs_pct`**: porcentaje 0–100 (50.00 = 50 %), no razón decimal (0.50). La división `/100.0` ocurre solo en el motor (§5.2 Q6) para que UI/Excel sigan legibles.

### 4.5 Campos-fonte verificados (verdad de campo por tabla)

| Linea del P&L | Tabla | Campo valor | Campo fecha | Filtros disponibles |
| :--- | :--- | :--- | :--- | :--- |
| Ingresos real (consolidado) | `invoices` | `total_without_tax` (Float) | `invoice_date` | fecha; (id_line/id_reference promueven a modo corte) |
| Ingresos real (corte) | `invoice_details` JOIN `invoices` | `value_without_tax` (Float) | `invoices.invoice_date` | + `id_reference` propio; linea via `product_references -> brands.id_line` |
| COGS real | `actual_costs` | `amount` (Float) | `cost_date` | fecha, `id_cost_center`, `id_reference` (nullable), linea via referencia |
| OPEX real | `actual_expenses` | `amount` (Numeric(15,2) -> float) | `expense_date` | fecha, `id_cost_center`; breakdown por `expense_type` |
| Ingreso presupuestado | `budget_lines` JOIN `budgets` JOIN `cost_centers` | `projected_amount` (Float) | `budget_date` | `line_type='income'`, `id_budget`, `id_cost_center`, linea via `cost_centers.id_line` |
| Gasto presupuestado | igual, `line_type='expense'` | `projected_amount` | `budget_date` | mismo (sin corte por linea/referencia, A-7) |
| Tasa de costo | `line_cost_rates` | `cogs_pct` (Numeric(5,2)) | `date_from`/`date_to` | vigencia al corte (§4.4) |

**No usar** (trampas confirmadas en código): `invoices.total_discount` (ya embebido en `total_without_tax`, A-2); `credits.*` (cartera a plazo, no NC — ver preámbulo); `budget_lines.payment_date` (semantica de caja, no de causación — solo la usa el cash-flow); `actual_costs.unit_cost * quantity` (usar `amount` directamente).

## 5. Especificación Funcional — `BudgetEngine.get_pnl()`

### 5.1 Firma

```python
def get_pnl(
    self,
    date_from: date,
    date_to: date,
    id_budget: Optional[int] = None,
    id_cost_center: Optional[int] = None,
    id_line: Optional[int] = None,
    id_reference: Optional[int] = None,
    include_breakdown: bool = False,
) -> Dict[str, Any]:
```

#### 5.1.1 Imports a adicionar en `budgetEngine.py`

```python
from datetime import date                          # extender el import existente de datetime
from sqlalchemy import and_, func, extract         # and_ nuevo; func/extract ya estan
from app.models import (                           # bloque nuevo (modelos core, no budget)
    Invoice as InvoiceModel,
    InvoiceDetail as InvoiceDetailModel,
    Reference as ReferenceModel,
    Brand as BrandModel,
)
from app.models.budget import (                    # extender el bloque existente
    LineCostRate as LineCostRateModel,
)
```

### 5.2 Queries exactas (SQLAlchemy legacy `db.query`, estilo del proyecto)

```python
slice_mode = (id_line is not None) or (id_reference is not None)   # §2; elige Q1a vs Q1b y anula Q3/Q5 (§5.4)
warnings: List[str] = []                                           # colector de meta.warnings (§6.1.3)
```

**Q0 — Resolver presupuesto (D-3):**

```python
budget_row = None
if id_budget is not None:
    budget_row = self.db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget).first()   # 404 lo resuelve el endpoint (§6.1)
else:
    budget_row = (self.db.query(BudgetModel)
        .filter(BudgetModel.budget_year == date_to.year,
                BudgetModel.status == "active",
                BudgetModel.is_scenario.is_(False))
        .order_by(BudgetModel.id_budget).first())
# budget_row None => todos los budgets del payload null + warning
```

**Q1a — Ingresos reales, modo consolidado (header, canónico):**

```python
revenues_actual = float(self.db.query(
    func.coalesce(func.sum(InvoiceModel.total_without_tax), 0.0)
).filter(
    InvoiceModel.invoice_date >= date_from,
    InvoiceModel.invoice_date <= date_to,
).scalar())
```

**Q1b — Ingresos reales, modo corte (detalle; D-1 aplica porque las NC negativas traen detalles):**

```python
q = (self.db.query(
        func.coalesce(func.sum(InvoiceDetailModel.value_without_tax), 0.0))
     .join(InvoiceModel, InvoiceDetailModel.id_invoice == InvoiceModel.id_invoice)
     .join(ReferenceModel, InvoiceDetailModel.id_reference == ReferenceModel.id_reference)
     .join(BrandModel, ReferenceModel.id_brand == BrandModel.id_brand)
     .filter(InvoiceModel.invoice_date >= date_from,
             InvoiceModel.invoice_date <= date_to))
if id_reference is not None:
    q = q.filter(InvoiceDetailModel.id_reference == id_reference)
if id_line is not None:
    q = q.filter(BrandModel.id_line == id_line)
revenues_actual = float(q.scalar())
```

> **JOINs internos, no EXISTS**: a nivel de detalle se suma el propio detalle (no hay fan-out que duplicar). Efecto colateral especificado en D-1: la fila con `id_reference` NULL queda fuera del corte ⇒ warning. El filtro de negocio `id_line` usa `brands.id_line`; no confundir con `cost_centers.id_line` (usado en Q4).

**Q2 — COGS real:**

```python
q = (self.db.query(func.coalesce(func.sum(ActualCostModel.amount), 0.0))
     .filter(ActualCostModel.cost_date >= date_from,
             ActualCostModel.cost_date <= date_to))
if id_cost_center is not None:
    q = q.filter(ActualCostModel.id_cost_center == id_cost_center)
if id_reference is not None:
    q = q.filter(ActualCostModel.id_reference == id_reference)
if id_line is not None:
    q = (q.join(ReferenceModel, ActualCostModel.id_reference == ReferenceModel.id_reference)
           .join(BrandModel, ReferenceModel.id_brand == BrandModel.id_brand)
           .filter(BrandModel.id_line == id_line))
cogs_actual = float(q.scalar())
```

**Q3 — OPEX real** (null en slice_mode; el desglose no tiene costo extra):

```python
opex_actual: Optional[float] = None
breakdown: Optional[List[Dict[str, Any]]] = None
if not slice_mode:
    if include_breakdown:
        rows = (self.db.query(
                    ActualExpenseModel.expense_type,
                    func.coalesce(func.sum(ActualExpenseModel.amount), 0.0))
                .filter(ActualExpenseModel.expense_date >= date_from,
                        ActualExpenseModel.expense_date <= date_to))
        if id_cost_center is not None:
            rows = rows.filter(ActualExpenseModel.id_cost_center == id_cost_center)
        grouped = rows.group_by(ActualExpenseModel.expense_type).all()
        breakdown = [{"category": t, "actual": round(float(a), 2)} for t, a in grouped]
        opex_actual = round(sum(float(a) for _t, a in grouped), 2)
    else:
        q3 = self.db.query(
            func.coalesce(func.sum(ActualExpenseModel.amount), 0.0)
        ).filter(ActualExpenseModel.expense_date >= date_from,
                 ActualExpenseModel.expense_date <= date_to)
        if id_cost_center is not None:
            q3 = q3.filter(ActualExpenseModel.id_cost_center == id_cost_center)
        opex_actual = float(q3.scalar())
```

**Q4/Q5 — Presupuesto por CECO** (helper privado `_budget_rows(line_type)`; alimenta BR-7/BR-10):

```python
def _budget_rows(self, resolved_id, date_from, date_to, line_type, id_cost_center, id_line):
    q = (self.db.query(
            BudgetLineModel.id_cost_center,
            CostCenterModel.id_line,
            func.coalesce(func.sum(BudgetLineModel.projected_amount), 0.0))
         .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
         .join(CostCenterModel, BudgetLineModel.id_cost_center == CostCenterModel.id_cost_center)
         .filter(BudgetModel.id_budget == resolved_id,
                 BudgetLineModel.line_type == line_type,      # "income" | "expense" (str-enum, patron cash-flow)
                 BudgetLineModel.budget_date >= date_from,
                 BudgetLineModel.budget_date <= date_to))
    if id_cost_center is not None:
        q = q.filter(BudgetLineModel.id_cost_center == id_cost_center)
    if id_line is not None and line_type == "income":
        q = q.filter(CostCenterModel.id_line == id_line)      # presupuesto de ingreso si es cortable por linea (BR-10)
    return q.group_by(BudgetLineModel.id_cost_center, CostCenterModel.id_line).all()
```

Reglas de invocación (resumen de §5.4):
- `budget_row is None` ⇒ Q4/Q5 no se ejecutan (budgets `null`).
- `id_reference is not None` ⇒ Q4/Q5 no se ejecutan (el presupuesto no conoce referencias, A-7).
- `slice_mode ∧ id_line is not None` ⇒ Q4 corre filtrada (ingreso presupuestado y `cogs.budget` **sí** se devuelven para la línea); Q5 no corre (gasto presupuestado sin corte).
- **Todos** los `behavior_type` entran a la sumatoria: `projected_amount` es el gasto planeado por causación; `variable_rate` es un mecanismo de simulación de caja (cash-flow) y **no** se aplica aquí (BR-16).

**Q6 — Tasas vigentes + ensamblado de `cogs.budget` con traza D-6 (BR-7/BR-21):**

```python
rates = (self.db.query(LineCostRateModel)
         .filter(LineCostRateModel.is_active.is_(True),
                 LineCostRateModel.date_from <= date_to,
                 LineCostRateModel.date_to >= date_to)
         .order_by(LineCostRateModel.id_line_cost_rate.desc())   # desempate §4.4.1
         .all())
pct_by_line: Dict[int, float] = {}
fallback_pct: Optional[float] = None
for r in rates:
    if r.id_line is None:
        fallback_pct = float(r.cogs_pct) if fallback_pct is None else fallback_pct
    else:
        pct_by_line.setdefault(r.id_line, float(r.cogs_pct))

income_rows = self._budget_rows(resolved_id, date_from, date_to, "income", id_cost_center, id_line)
q4_ran = (resolved_id is not None) and (id_reference is None)      # gate matriz §5.4: referencia anula presupuesto
revenues_budget = round(float(sum(r[2] for r in income_rows)), 2) if q4_ran else None   # BR-11 (errata I-2)

cogs_budget: Optional[float] = None
cogs_trace: List[Dict[str, Any]] = []
if resolved_id is not None:
    cc_codes = dict(self.db.query(
        CostCenterModel.id_cost_center, CostCenterModel.cost_center_code).all())   # Q7 (D-6)
    total, applied = 0.0, False
    for cc, line, amount in income_rows:
        pct = pct_by_line.get(line) if line is not None else None
        source = "line"
        if pct is None:
            pct, source = fallback_pct, "global"          # red de respaldo (D-6)
        if pct is None:
            warnings.append(f"Cost center {cc} has income budget {float(amount):.2f} and no applicable cost rate; excluded from cogs.budget")
            continue
        contribution = round(float(amount) * pct / 100.0, 2)
        total += contribution
        applied = True
        cogs_trace.append({"id_cost_center": cc, "cost_center_code": cc_codes.get(cc),
                           "id_line": line, "pct": pct, "source": source,
                           "income_budget": round(float(amount), 2),
                           "cogs_contribution": contribution})            # BR-21
    cogs_budget = round(total, 2) if applied else None    # invariante == SUM(cogs_contribution)
    if cogs_budget is None and income_rows:
        warnings.append("No cost rate configured (line or global) for the period: cogs.budget is null")
```

### 5.3 Cálculos derivados (regla exacta, null-safe)

```python
gross_actual = round(revenues_actual - cogs_actual, 2)
opex_a = opex_actual if opex_actual is not None else 0.0
operating_actual = round(gross_actual - opex_a, 2)          # slice: operating == gross (BR-11)

opex_budget = round(float(sum(r[2] for r in expense_rows)), 2) if (Q5 corrio) else None

gross_budget = (round(revenues_budget - cogs_budget, 2)
                if revenues_budget is not None and cogs_budget is not None else None)   # BR-8
operating_budget = (round(gross_budget - opex_budget, 2)
                    if gross_budget is not None and opex_budget is not None else None)
```

| Métrica | Fórmula (D-4) | Null si |
| :--- | :--- | :--- |
| `revenues.variance` | `actual − budget` | presupuesto null |
| `cogs.variance` | `budget − actual` | presupuesto null |
| `opex.variance` | `budget − actual` | presupuesto null |
| `gross_profit.variance` / `operating_profit.variance` | `actual − budget` | presupuesto null |
| `*.variance_pct` | `variance / abs(budget) * 100` | budget null o 0 |
| `gross_profit.margin_pct` | `gross_actual / revenues_actual * 100` | `revenues_actual == 0` (A-9) |
| `operating_profit.margin_pct` | `operating_actual / revenues_actual * 100` | idem |
| `*.margin_pct_budget` | idem con cifras presupuestadas | `revenues_budget` null/0 o presupuesto de la utilidad null |

Redondeo: 2 dec para valores, 1 dec para márgenes, `round()` de Python (banker's rounding). **Documentado**: el `46.6` del JSON HSpec es truncamiento; el motor devuelve `46.7` para 70.000/150.000 (AC-5 fija la convención).

### 5.4 Matriz de filtros (cuánto aplica cada dimensión a cada línea)

| Filtro | Ingresos | COGS | OPEX | Budget ingresos | Budget COGS (tasa) | Budget OPEX |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `date_from..date_to` | ✔ `invoice_date` | ✔ `cost_date` | ✔ `expense_date` | ✔ `budget_date` | ✔ derivado | ✔ |
| `id_cost_center` | ✘ (→ `meta.not_filterable`, BR-9) | ✔ | ✔ | ✔ | ✔ (per-CC, BR-7) | ✔ |
| `id_line` | ✔ (activa modo corte vía `brands`) | ✔ (vía referencia→marca) | ✘ null | ✔ (vía `cc.id_line`, BR-10) | ✔ (tasa de esa línea) | ✘ null |
| `id_reference` | ✔ (activa modo corte) | ✔ (NULL=excluida) | ✘ null | ✘ null | ✘ null | ✘ null |

### 5.5 Transaccionalidad

`get_pnl` es 100 % lectura (`SELECT`s; ningún `add/flush/commit/delete/update`). La sesión la cierra `get_db` como siempre. Bajo concurrencia no adquiere locks (Read Committed es aceptable: el P&L es analítico; BR-19).

## 6. Contratos de API

Ambos grupos requieren JWT (`Depends(get_current_user)`), alineado con el resto de `analytics.py`.

### 6.1 `GET /budget/analytics/pnl`

```python
@router.get("/pnl", response_model=PnLResponse)
def get_pnl(
    date_from: date = Query(..., description="Period start (inclusive, accrual dates)"),
    date_to: date = Query(..., description="Period end (inclusive; governs budget year and rate validity)"),
    id_budget: Optional[int] = Query(None, description="Explicit budget ID (also allows scenario clones). Default: active budget of year(date_to)"),
    id_cost_center: Optional[int] = Query(None, description="Filter COGS/OPEX/budget by cost center (does NOT apply to revenues)"),
    id_line: Optional[int] = Query(None, description="Slice revenues/COGS by product line (brand mapping)"),
    id_reference: Optional[int] = Query(None, description="Slice revenues/COGS by product reference"),
    include_breakdown: bool = Query(False, description="Add opex.breakdown by expense_type (actual only)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pilar 1 - Accrual P&L: actual vs budget vs variance with margins."""
    engine = BudgetEngine(db)
    return engine.get_pnl(
        date_from=date_from, date_to=date_to, id_budget=id_budget,
        id_cost_center=id_cost_center, id_line=id_line, id_reference=id_reference,
        include_breakdown=include_breakdown,
    )
```

**Validaciones pre-engine (en el endpoint):** `date_from > date_to` ⇒ 400 (E-1); FKs inexistentes ⇒ `Exceptions.register_not_found(...)` (404) usando `crud.get_cost_center_by_id` y lookup equivalente para `lines`/`product_references`/`budgets`.

#### 6.1.1 Respuesta 200 — ejemplo canónico (golden seed §11)

```json
{
  "period": { "from": "2026-01-01", "to": "2026-01-31" },
  "pnl_statement": {
    "revenues":         { "actual": 150000.0, "budget": 160000.0, "variance": -10000.0, "variance_pct": -6.25 },
    "cogs":             { "actual": 80000.0,  "budget": 83000.0,  "variance": 3000.0,   "variance_pct": 3.61 },
    "gross_profit":     { "actual": 70000.0,  "budget": 77000.0,  "variance": -7000.0,  "variance_pct": -9.09, "margin_pct": 46.7, "margin_pct_budget": 48.1 },
    "opex":             { "actual": 30000.0,  "budget": 28000.0,  "variance": -2000.0,  "variance_pct": -7.14, "breakdown": null },
    "operating_profit": { "actual": 40000.0,  "budget": 49000.0,  "variance": -9000.0,  "variance_pct": -18.37, "margin_pct": 26.7, "margin_pct_budget": 30.6 }
  },
  "meta": {
    "mode": "consolidated",
    "budget_source": { "id_budget": 1, "budget_name": "Presupuesto 2026", "status": "active" },
    "filters": { "date_from": "2026-01-01", "date_to": "2026-01-31", "id_budget": null, "id_cost_center": null, "id_line": null, "id_reference": null, "include_breakdown": false },
    "not_filterable": [],
    "cogs_budget_trace": [
      { "id_cost_center": 1, "cost_center_code": "TD-ENV", "id_line": 1,    "pct": 50.0, "source": "line",   "income_budget": 100000.0, "cogs_contribution": 50000.0 },
      { "id_cost_center": 2, "cost_center_code": "MATRIZ", "id_line": null, "pct": 55.0, "source": "global", "income_budget": 60000.0,  "cogs_contribution": 33000.0 }
    ],
    "warnings": []
  }
}
```

#### 6.1.2 Respuesta modo corte (`?id_line=L1`, mismos datos seed)

```json
{
  "pnl_statement": {
    "revenues":         { "actual": 150000.0, "budget": 100000.0, "variance": 50000.0, "variance_pct": 50.0 },
    "cogs":             { "actual": 50000.0,  "budget": 50000.0,  "variance": 0.0, "variance_pct": 0.0 },
    "gross_profit":     { "actual": 100000.0, "budget": 50000.0,  "variance": 50000.0, "variance_pct": 100.0, "margin_pct": 66.7, "margin_pct_budget": 50.0 },
    "opex":             { "actual": null, "budget": null, "variance": null, "variance_pct": null, "breakdown": null },
    "operating_profit": { "actual": 100000.0, "budget": null, "variance": null, "variance_pct": null, "margin_pct": 66.7, "margin_pct_budget": null }
  },
  "meta": {
    "mode": "slice",
    "not_filterable": ["opex (no line/reference dimension)", "opex_budget (no slice support in v1)"],
    "cogs_budget_trace": [
      { "id_cost_center": 1, "cost_center_code": "TD-ENV", "id_line": 1, "pct": 50.0, "source": "line", "income_budget": 100000.0, "cogs_contribution": 50000.0 }
    ],
    "warnings": []
  }
}
```

> En slice, `operating_profit` replica a `gross_profit` (no se resta OPEX inexistente, BR-11): la UI debe mostrar la etiqueta *EBITDA no disponible en corte de línea*.

#### 6.1.3 Diccionario de `meta`

| Campo | Regla |
| :--- | :--- |
| `mode` | `"slice"` si llegó `id_line` o `id_reference`; `"consolidated"` en otro caso. |
| `budget_source` | `{id_budget, budget_name, status}` del presupuesto usado; `null` si no hay (D-3). |
| `filters` | Eco literal de los query params recibidos (incluidos los `null`). |
| `not_filterable` | Líneas del statement que **no** recibieron el filtro pedido (BR-9, A-7); cadenas estables para la UI. |
| `cogs_budget_trace` | Auditoría de la cadena D-6: un ítem por CECO cuyo ingreso presupuestado contribuyó a `cogs.budget`, en el orden devuelto por Q4. `source` = `"line"` (tasa de la línea del CECO) o `"global"` (respaldo `id_line = NULL`). CECOs excluidos por ausencia total de tasa NO aparecen: se denuncian en `warnings`. Invariante de contrato: `round(Σ cogs_contribution, 2) == cogs.budget` (BR-21, AC-16). Se emite también en modo corte (solo CECOs de la línea filtrada, BR-10); con `cogs.budget = null` ⇒ lista `[]`. |
| `warnings` | Casos: CECO excluido de `cogs.budget` sin tasa (BR-15); `cogs.budget` null por ausencia total de tasas; rango cruzando años (`"period crosses fiscal years; budget scoped to year(date_to)"`); >1 presupuesto active (se tomó el menor id); presupuesto `id_budget` con `is_scenario=True` (`"Comparing against scenario budget"`); NC/facturas negativas sin `id_reference` en modo corte (conteo, D-1). |

### 6.2 CRUD de tasas: `app/api/budget/lineCostRate.py` (montado en prefix `/budget/line-cost-rate`)

Espejo del estilo de `budgetScenario.py` (auth JWT en cada ruta, `Exceptions.register_not_found` en 404, filtros como query params, `skip/limit`):

| Método | Ruta | Notas |
| :--- | :--- | :--- |
| GET | `/` | Params: `id_line?`, `active_only: bool = False`, `date?` (solo vigentes a `date`, aplica §4.4.1), `skip=0`, `limit=100`. `response_model=List[LineCostRate]` |
| GET | `/{id_line_cost_rate}` | 404 si no existe |
| POST | `/` | Body `LineCostRateCreate`; valida BR-12/BR-13; FK `id_line` inexistente ⇒ 404 |
| PUT | `/{id_line_cost_rate}` | Body `LineCostRateUpdate` (merge parcial + mismas validaciones, excluyendo el propio id del chequeo de solape) |
| DELETE | `/{id_line_cost_rate}` | Borrado físico (la auditoría se hace con `is_active=False` vía PUT) |

## 7. Contrato CRUD (`app/crud/budget/lineCostRate.py`)

```python
def get_line_cost_rates(db, id_line=None, active_only=False, date_ref=None, skip=0, limit=100) -> List[LineCostRate]
def get_line_cost_rate_by_id(db, id_line_cost_rate: int) -> Optional[LineCostRate]
def _rate_period_invalid(date_from, date_to) -> bool        # date_from > date_to  (BR-12)
def _rate_overlaps(db, id_line, date_from, date_to, exclude_id=None) -> bool   # solo filas is_active (BR-13)
def create_line_cost_rate(db, payload: LineCostRateCreate) -> LineCostRate     # HTTPException 400 via helpers (E-4/E-5)
def update_line_cost_rate(db, id_line_cost_rate: int, payload: LineCostRateUpdate) -> Optional[LineCostRate]
def delete_line_cost_rate(db, id_line_cost_rate: int) -> LineCostRate
```

- Solape NULL-safe: base `date_from <= :new_to AND date_to >= :new_from AND is_active IS TRUE`; grupo específico `.filter(LineCostRateModel.id_line == id_line)`, grupo global `.filter(LineCostRateModel.id_line.is_(None))`.
- `update`: merge de campos sobre el registro (solo los no-None) antes de revalidar.
- Estilo: legacy `db.query`, `db.commit()` al final de create/update/delete, `db.refresh` antes de retornar (patrón `costCenter.py`).

## 8. Requisitos No Funcionales

### 8.1 Rendimiento y escalabilidad

- **Estrategia de agregación (Action-Item 2 del HSpec): `GROUP BY` + `SUM`, 6–8 consultas por petición (Q7, condicional y trivial: mapa CECO→código para `cogs_budget_trace`, D-6), sin window functions.** El P&L devuelve escalares por línea (no hay ranking/acumulados que las justifiquen), y el patrón `db.query(...).group_by(...)` es el vigente en `project_cash_flow`. La única complejidad de agrupación es Q4/Q5 (por CECO; cardinalidad = #cost_centers, decenas).
- Latencia objetivo: < 500 ms en dev Docker con 100 k filas en cada tabla fuente.
- Índices opcionales sugeridos cuando las tablas superen ~100 k filas (hoy innecesarios; solo `CREATE INDEX`, sin ALTER):

```sql
CREATE INDEX IF NOT EXISTS ix_invoices_invoice_date        ON invoices (invoice_date);
CREATE INDEX IF NOT EXISTS ix_actual_costs_cost_date       ON actual_costs (cost_date);
CREATE INDEX IF NOT EXISTS ix_actual_expenses_expense_date ON actual_expenses (expense_date);
CREATE INDEX IF NOT EXISTS ix_budget_lines_budget_date     ON budget_lines (budget_date);
```

- Sin cacheo en v1 (requisito del HSpec: tiempo real). Si Q0/Q4/Q5 dominaran el costo, la memoización del presupuesto es tarea del sprint de escenarios (`budget_scenarios.results` es el lugar natural), no de este motor.

### 8.2 Seguridad

- JWT obligatorio en los 6 endpoints nuevos. Sin control por roles en v1 (coherente con `analytics.py`); **recomendación registrada**: limitar el mantenimiento de tasas (POST/PUT/DELETE `/line-cost-rate`) a roles de gerencia en el sprint de frontend — el P&L es datos sensibles bottom-line.
- **Gobernanza de la tasa global (D-6)**: al apalancar todos los CECOs sin línea, su `cogs_pct` debe fijarse como promedio ponderado por ingreso y revisarse cada vigencia; `meta.cogs_budget_trace` hace visible ante gerencia cada uso (`source: "global"`) para evitar que el respaldo se vuelva regla silenciosa.
- Sin archivos ni escritura operativa: superficie de entrada acotada a tipos `date`/`int` que valida FastAPI (SQLAlchemy parametriza; no hay string interpolation SQL).

### 8.3 Disponibilidad y operación

- Lecturas síncronas HTTP; sin jobs. La tabla de tasas se mantiene por API; el seed inicial es responsabilidad de gerencia tras el deploy (AC-2).
- Failure mode: cualquier excepción ⇒ 500 estándar; el P&L nunca deja estado a medio escribir (read-only, §5.5). Recovery de tasas mal capturadas: PUT `is_active=false` restaura el cálculo sin tocar datos operativos.

### 8.4 Compatibilidad aguas abajo (regression surface)

- `project_cash_flow` intacto: solo se **añade** el método `get_pnl` + helpers (§3.2 #12; AC-13).
- `budget-vs-actual` y `tracking/{id_budget}` (stubs TODO en `analytics.py`) permanecen sin cambios — este endpoint **no** los implementa, son comparaciones por CECO, no statement.
- `LineTypeEnum`/`BehaviorTypeEnum` no se modifican; no se toca `upload.py`.
- Rutas nuevas sin colisión: no existía `/pnl` ni `/line-cost-rate` en el prefijo `/budget`.
- Frontend: ningún consumidor actual de estos payloads (superficie = solo adiciones OpenAPI).

## 9. Reglas de Negocio (numeradas, trazables)

| ID | Regla | Fuente |
| :-- | :--- | :--- |
| BR-1 | Ingresos Netos = `SUM(invoices.total_without_tax)` por `invoice_date`; base neta de IVA, homogénea con `budget_lines.income` (NET) | A-1, HSpec §3 |
| BR-2 | Las devoluciones son facturas con importes negativos y restan dentro de la sumatoria; **no** existe línea `sales_returns` en el payload | **D-1** |
| BR-3 | No se resta `total_discount` ni `invoice_details.discount` (ya embebidos en el valor sin IVA) | A-2 |
| BR-4 | Modo consolidado suma encabezados; modo corte suma **detalles** (`invoice_details.value_without_tax`) de las filas que coinciden con el filtro | §5.2 Q1 |
| BR-5 | COGS = `SUM(actual_costs.amount)` por `cost_date`; OPEX = `SUM(actual_expenses.amount)` por `expense_date` (causación, no pago) | HSpec §2/§3 |
| BR-6 | `gross_profit = revenues − cogs`; `operating_profit = gross_profit − opex` (cascada del HSpec §3) | HSpec §3 |
| BR-7 | `cogs.budget = Σ_cc (ingreso_presupuestado(cc) × pct(línea(cc)) / 100)` con cadena de fallback: tasa de línea → tasa global → exclusión | **D-2** |
| BR-8 | Favorability chain: `cogs.budget = null ⇒ gross.budget = null ⇒ operating.budget = null`; nunca se asume costo presupuestado 0 | §2, §5.3 |
| BR-9 | `id_cost_center` **no** aplica a ingresos; el valor devuelto sigue siendo el consolidado y se reporta en `meta.not_filterable` | A-6 |
| BR-10 | En corte por `id_line`: presupuesto de ingresos se filtra vía `cost_centers.id_line`; OPEX real y gasto presupuestado devuelven `null`; `operating_profit` del slice iguala a `gross_profit` (sin sustraer OPEX) con nota en `not_filterable` | A-7 + D-2 |
| BR-11 | Un slice por `id_reference` es el caso más estricto: todo `budget` es `null` (el plan no conoce referencias) | A-7 |
| BR-12 | Toda tasa: `date_to >= date_from` y `0 <= cogs_pct <= 100`; violación ⇒ 400 (E-4) / 422 | §4.4, §7 |
| BR-13 | Dos tasas activas de la misma línea (o dos globales) no pueden solapar vigencias; POST/PUT con solape ⇒ 400 (E-5) | §4.4.3 |
| BR-14 | La vigencia de la tasa se resuelve contra `date_to` del periodo consultado (§4.4.1) | §4.4 |
| BR-15 | CECOs con ingreso presupuestado y sin pct aplicable se excluyen de `cogs.budget` con warning por CECO; si no aplica ninguno ⇒ `cogs.budget = null` | §4.4.2 |
| BR-16 | Q5 suma **todos** los `behavior_type` de `line_type='expense'` (`variable_rate` pertenece a la mecánica de caja, no a P&L) | §5.2 Q4/Q5 |
| BR-17 | Presupuesto por defecto: `status='active' ∧ is_scenario=False ∧ budget_year=year(date_to)`; `id_budget` explícito manda (incluidos escenarios, con warning) | **D-3** |
| BR-18 | Varianzas según D-4; márgenes siempre sobre cifras reales (+ aditivo presupuestado); `null` si el denominador es `null` o `0`; valores redondean a 2 dec, márgenes a 1 dec | D-4, A-9 |
| BR-19 | El motor no escribe: ninguna llamada a `add/commit/delete/update` dentro de `get_pnl` | §5.5 |
| BR-20 | `line_cost_rates` es la única fuente del pct y el P&L **nunca se persiste** (capa de agregación, requisito §2 del HSpec) | HSpec §2 |
| BR-21 | `meta.cogs_budget_trace` se emite siempre (`[]` si `cogs.budget` es null); invariante contractual `round(Σ cogs_contribution, 2) == cogs.budget`; ningún ítem con `source` fuera de `line`/`global` | **D-6** |

## 10. Catálogo de Errores

| # | Código | Trigger | `detail` |
| :-- | :--- | :--- | :--- |
| E-1 | 400 | `date_from > date_to` (P&L y query `date` de tasas) | `"date_from must be on or before date_to"` |
| E-2 | 404 | `id_cost_center` / `id_line` / `id_reference` / `id_budget` inexistente | patrón `Exceptions.register_not_found(...)` |
| E-3 | 422 | Fecha mal formatada, `cogs_pct` fuera de [0,100], query params obligatorios ausentes | nativo FastAPI/Pydantic |
| E-4 | 400 | POST/PUT tasa con vigencia invertida (BR-12) | `"date_to must be on or after date_from"` |
| E-5 | 400 | POST/PUT tasa con solape activo (BR-13) | `"Overlapping active rate for this line (or global) period; deactivate or adjust dates first"` |
| E-6 | — | Sin presupuesto active | **no es error**: 200 con budgets `null` + warning (D-3) |
| E-7 | 401/403 | Sin JWT | estándar FastAPI |
| E-8 | 500 | Cualquier otra excepción BD/parseo | `"Error computing P&L: {e}"` (patrón analítica) |
| E-9 | 404 | GET/PUT/DELETE tasa por id inexistente | patrón `Exceptions.register_not_found` |

## 11. Criterios de Aceptación (golden seed determinístico)

**Seed de prueba** (BD dev limpia, `docker compose -f docker-compose-dev.yaml up`, backend :8003):

- Catálogos: línea `L1` y línea `L2`; marca `X ∈ L1`; referencia `R1 ∈ X`; CECO `A` (id_line=L1), CECO `B` (id_line=NULL), CECO `C` (id_line=L2, sin tasa).
- Tasas (vía API §6.2): `L1: cogs_pct=50.00`, `2026-01-01→2026-12-31`; **global**: `id_line=NULL, cogs_pct=55.00`, mismo rango.
- Presupuesto `Presupuesto 2026` (`status='active'`, `is_scenario=False`, `budget_year=2026`) con líneas `budget_date` en enero/2026: income A = 100 000; income B = 60 000; expense A = 15 000; expense B = 13 000.
- Ejecución enero: invoices `INV-1 total_without_tax=170000` (detalle R1 = 170000) + `NC-1 total_without_tax=-20000` (detalle R1 = −20000, D-1) ⇒ **150 000**; `actual_costs` cc A: 50 000 (ref R1) + 30 000 (ref NULL) ⇒ **80 000**; `actual_expenses`: cc A 18 000 (`expense_type='NOMINAS'`), cc B 12 000 (`'ARRENDAMIENTO'`) ⇒ **30 000**.

| AC | Criterio |
| :-- | :--- |
| **AC-1** (esquema) | Tras restart del backend con el modelo registrado: `line_cost_rates` existe (create_all); `GET /budget/line-cost-rate/` ⇒ 200 `[]`; el modelo importa sin error vía `from app.models.budget import LineCostRate`. |
| **AC-2** (CRUD tasas) | POST L1 50 % ⇒ 200; POST L1 con 2026-06-01→2026-12-31 ⇒ **400 (E-5)**; POST global 55 % ⇒ 200; POST con `cogs_pct=101` ⇒ 422 (E-3/BR-12); PUT fecha invertida ⇒ 400 (E-4). |
| **AC-3** (golden) | `GET /budget/analytics/pnl?date_from=2026-01-01&date_to=2026-01-31` ⇒ 200 con valores exactos de §6.1.1: `revenues{150000, 160000, −10000, −6.25}`; `cogs{80000, 83000, +3000, 3.61}` (nota: `100000×50 % + 60000×55 % = 83000`); `gross{70000, 77000, −7000, margin 46.7/48.1}`; `opex{30000, 28000, −2000, −7.14}`; `operating{40000, 49000, −9000, 26.7/30.6}`; `meta.mode="consolidated"` con `budget_source.id_budget` poblado y `meta.cogs_budget_trace` de 2 ítems: cc A (pct 50.0, source `line`, contribución 50000.0) y cc B (pct 55.0, source `global`, contribución 33000.0). |
| **AC-4** (D-1) | Eliminando la factura `NC-1` ⇒ `revenues.actual == 170000.0` — prueba que la NC negativa restaba exactamente 20 000 dentro de la sumatoria (sin línea separada). |
| **AC-5** (rounding) | Convención fijada: el truncamiento del ejemplo HSpec (46.6) es reemplazado por `round()` real (46.7 para 70.000/150.000). Cualquier otro valor ⇒ AC-3 falla. |
| **AC-6** (sin presupuesto, E-6) | Cambiar `budget.status='archived'` ⇒ 200 con todos los `budget/variance/margin_pct_budget = null`, `actual` intacto, `meta.budget_source=null`, warning `"No active non-scenario budget for 2026"`; **nunca** 500. |
| **AC-7** (escenario, BR-17) | Clonar el presupuesto (flag `is_scenario=True`, status `draft`) vía `POST clone-for-scenario` o SQL, y llamar `?id_budget=<clon>` ⇒ usa el clon y `meta.warnings` contiene `"Comparing against scenario budget"`. |
| **AC-8** (BR-15/BR-8) | PUT: desactivar la tasa global (dejar solo L1) ⇒ `cogs.budget == 50000.0` (solo cc A) + warning con el cc B (`60000.0`); desactivar también la de L1 ⇒ `cogs.budget=null` ⇒ `gross_profit.budget=null` ⇒ `operating_profit.budget=null` (favorability chain); en ambos pasos `meta.cogs_budget_trace` se reduce al ítem de cc A y el invariante BR-21 se conserva. |
| **AC-9** (corte BR-4/BR-10) | `?id_line=L1` ⇒ `mode="slice"`; `revenues.actual==150000.0` (detalles R1: 170000−20000), `cogs.actual==50000.0` (la fila de 30 000 sin referencia queda fuera), `revenues.budget==100000.0` (cc A), `cogs.budget==50000.0`, `opex` y `opex_budget` `null`, `operating == gross` (BR-11), `not_filterable` incluye `opex`; los valores de §6.1.2 reproducidos. |
| **AC-10** (cc filter BR-9) | `?id_cost_center=A` ⇒ `cogs.actual==80000.0`, `opex.actual==18000.0`, budgets A-only (`revenues.budget==100000`, `cogs.budget==50000`, `opex.budget==15000`); `revenues.actual` sigue `150000.0` (BR-9) y `not_filterable` incluye `"revenues (no cost-center dimension)"`. |
| **AC-11** (cero-margen) | Consultar `2027-01-01..2027-01-31` (sin datos) ⇒ todos `actual=0.0`, `margin_pct=null` (A-9, sin ZeroDivisionError), 200 OK. |
| **AC-12** (read-only) | Antes/después de 5 llamadas a `get_pnl`: `SELECT count(*)` idéntico en invoices, invoice_details, actual_costs, actual_expenses, budget_lines, line_cost_rates. |
| **AC-13** (regresión) | `GET /budget/analytics/cash-flow-projection?budget_year=2026` responde 200 con los mismos valores que antes del cambio; `budget-vs-actual` y `tracking` siguen con su comportamiento stub sin cambios. |
| **AC-14** (auth) | GET `/budget/analytics/pnl...` y GET `/budget/line-cost-rate/` sin token ⇒ 401/403. |
| **AC-15** (OpenAPI) | `/docs` lista `GET /budget/analytics/pnl` (tag Budget Analytics) y las 5 rutas de `/budget/line-cost-rate` (tag Line Cost Rates) con `response_model` correcto. |
| **AC-16** (invariante D-6) | En toda combinación de filtros con `cogs.budget` no-null: `round(sum(trace[*].cogs_contribution), 2) == pnl_statement.cogs.budget` exacto; todo `source` pertenece a {`line`, `global`}; con `?id_cost_center=A` el trace tiene exactamente 1 ítem (cc A, source `line`); con `budget=null` (AC-6) trace = `[]`. |

## 12. Estrategia de Pruebas (el proyecto no tiene test suite)

1. **Smoke curl con golden seed**: cargar tasas por API (§6.2), insertar el resto del seed §11 vía SQL o los ETLs existentes (`upload/actual-costs`, `upload/actual-expenses`, `budget-plan-*`), y ejecutar:
   ```bash
   curl "http://127.0.0.1:8003/budget/analytics/pnl?date_from=2026-01-01&date_to=2026-01-31" \
     -H "Authorization: Bearer $TOKEN"
   ```
2. **Verificación SQL cruzada**: para cada línea del payload, la consulta de §4.5 con los mismos WHERE debe coincidir ±0.01 (ej. `SELECT SUM(total_without_tax) FROM invoices WHERE invoice_date BETWEEN '2026-01-01' AND '2026-01-31'`).
3. **Matriz de filtros**: AC-6..AC-10 combinando parámetros y validando `meta` (la sección más propensa a regresión semántica).
4. **Ciclo de vida de tasas**: POST → PUT de vigencia → solape 400 → PUT is_active=false; y el efecto de cada paso sobre `cogs.budget` (AC-8).
5. Recomendado (no bloqueante): fijar AC-3/AC-8/AC-9 como script `crm_backend/test/pnl_engine_smoke.py` idempotente contra BD dev.

## 13. Supuestos y Dependencias

- **Dep-BD**: Postgres 16; la tabla nueva se crea sola con `create_all` al desplegar el modelo (orden: deploy → crear tasas → exponer P&L). Sin ALTERs.
- **Datos**: los descuentos comerciales ya están aplicados dentro de `total_without_tax` (A-2). *Si una validación contra datos SIIGO reales muestra lo contrario, la corrección es restar el descuento en Q1/Q1b únicamente; el resto del motor no cambia.*
- **Datos**: las devoluciones de venta se cargarán a `invoices` con encabezado y detalles negativos y `id_reference` poblado en los detalles para que el corte por línea funcione (D-1); una NC sin referencia solo afecta el consolidado (warning en slice).
- **Datos**: las tasas `cogs_pct` son definición de gerencia por línea y vigencia; el seed inicial es responsabilidad del negocio, no del ETL.
- **Granularidad**: tasa solo por línea, **sin** dimensión de temporada (D-5). Extensión futura sin rompe-contrato: columna nullable `id_collection` en `line_cost_rates` + resolver colección→línea en Q6.
- **Nomenclatura de ruta**: el HSpec sugería `/budget/engine/pnl`; se monta en el router de analítica existente ⇒ **ruta final `GET /budget/analytics/pnl`** (misma familia que cash-flow; se evita un prefijo `/engine` huérfano). Cambio de nombre trivial si el stakeholder lo prefiere.
- **Año cruzado**: si `date_from..date_to` cruza años fiscales, el presupuesto comparado es el de `year(date_to)` con warning. Prorrateo entre dos presupuestos = mejora futura fuera de alcance.
- **Cash-flow vs P&L**: Q5 suma gastos de presupuesto por causación (BR-16), mientras `project_cash_flow` aplica `variable_rate` a las líneas variables (caja). La divergencia entre ambas cifras es esperable y documentada; no son contractivas.

## 14. Matriz de Trazabilidad (HSpec → especificación)

| HSpec | Estado | Dónde |
| :--- | :--- | :--- |
| §1 Objetivo (motor de agregación en tiempo real, sin tablas de resultados) | Aceptado | §1, BR-19/20, §5.5 |
| §2 Fuente ingresos `invoices` vs `actual_incomes` | **Resuelto**: `actual_incomes` no existe ⇒ `invoices` | Preámbulo, §5.2 Q1 |
| §2 Fuentes COGS/OPEX | Aceptado (tablas verificadas con sus campos reales) | §4.5 |
| §2 Fuentes de presupuesto | Aceptado + **nueva entidad** (no existía presupuesto de costos) | D-2, §4 |
| §3 Estructura 1-2-3 (Ingresos → Bruta → Operativa) | Aceptado con nomenclatura del payload | §6.1.1, BR-6 |
| §3 Métricas Margen Bruto/Operativo % | Aceptado (sobre real + aditivo presupuestado) | §5.3, BR-18 |
| §4 Filtros fecha/CECO/referencia-línea | Aceptado + semántica por dimensión | §5.4, BR-9/10/11 |
| §5 Payload actual/budget/variance | Aceptado; se añaden `variance_pct`, `margin_pct_budget` y `meta` (no breakantes) | §4.3.2, §6.1 |
| §6 Action-1: fuente exacta de ingresos | **Respondido**: `invoices.total_without_tax` (header) / `invoice_details.value_without_tax` (corte) | §5.2 |
| §6 Action-2: window functions vs GROUP BY | **Respondido**: GROUP BY/SUM, 6–7 queries, sin window functions | §8.1 |
| §6 Action-3: impacto de notas de crédito | **Respondido**: facturas negativas dentro de la sumatoria (D-1); tabla `credits` descartada (es cartera) | §0, BR-2 |
| (nuevo) Selección de presupuesto y escenarios | Especificado | D-3, BR-17 |
| (nuevo) Convención de signos, márgenes, redondeos | Especificada y auditable | D-4, BR-18, AC-5 |
| (nuevo) Gobernanza y auditoría de la tasa de respaldo | Especificado | D-6, §4.4.2, §5.2 Q6, §6.1.3, BR-21, AC-16 |

## 15. Checklist de Implementación (orden recomendado)

1. [x] Modelo `lineCostRate.py` + registros en `app/models/budget/__init__.py` y `app/models/__init__.py` (§3.2 #1–3) ⇒ AC-1.
2. [x] Schemas `lineCostRate.py` + bloque `PnL*` en `schemas/budget/budget.py` + `__init__.py` de schemas (§3.2 #4–7).
3. [x] CRUD `lineCostRate.py` (+ validaciones BR-12/13) y registro en `crud/budget/__init__.py` (§3.2 #8–9).
4. [x] API `lineCostRate.py` (5 rutas) + include en `api/budget/__init__.py` (§3.2 #10–11) ⇒ AC-2.
5. [x] `BudgetEngine`: imports nuevos (§5.1.1) + `get_pnl()` + helpers `_budget_rows()`/resolución de tasas (§5.2 Q6) ⇒ smoke SQL cruzado §12.2.
6. [x] Endpoint `GET /pnl` en `analytics.py` con validaciones E-1/E-2 (§6.1) ⇒ cerrar AC-3..AC-15.
7. [x] Verificar `/docs` (OpenAPI) con las 6 rutas nuevas y el `response_model` completo.
8. [ ] Comunicar el contrato §6.1 (payload + `meta`) al equipo de frontend para el dashboard Pilar 1.

---

## 16. Notas de implementación (errata v1.2 — 2026-09-04)

Implementación ejecutada por el equipo backend según §15 (13 archivos de §3.2; `budgetEngine.py` puro-aditivo +386/−0, `project_cash_flow` intacto). Verificación: golden seed §11 ejecutado en schema aislado de la BD dev ⇒ **86/86 checks AC-1..AC-16 PASS**; regresión AC-13 byte-a-byte contra baseline. Resolución de los hallazgos del implementador:

| # | Hallazgo | Resolución |
| :-- | :--- | :--- |
| I-1 | §5.2 Q1b tenía JOIN tautológico (`ReferenceModel.id_brand == ReferenceModel.id_brand`) | **Corregido en el texto** (ahora `== BrandModel.id_brand`, igual que Q2); el código ya implementa la forma correcta |
| I-2 | §5.2 Q6 `revenues_budget ... if income_rows or resolved_id` violaba BR-11 en slice por `id_reference` (devolvía 0.0 donde el contrato aprobado de §5.4 exige `null`) | **Corregido en el texto**: gate explícito `q4_ran`; la matriz §5.4 (norma aprobada) manda sobre el pseudo-código |
| I-3 | E-1 del §10 mencionaba el query param `date` de tasas | Aclarado: E-1 aplica solo a `/pnl`; vigencia invertida de bodies queda cubierta por E-4 |
| I-4 | Warnings adicionales sin texto literal en spec (`>1 active budget`, conteo NC sin `id_reference` en corte, `not_filterable` de budgets en slice por referencia) | Aceptados como adiciones a §6.1.3 (estables, en inglés, estilo proyecto) |
| I-5 | §5.1.1 pedía imports (`and_`, `date` en schemas) innecesarios tras I-1/I-2 | Omitidos en el código; sin impacto contractual |
| I-6 | Swagger UI servido en `/` (no `/docs`); AC-15 verificado vía `GET /openapi.json` | Nota operativa, sin cambio de spec |
| I-7 | **Bug preexistente, fuera de alcance de esta spec**: `budget_lines.behavior_type server_default="fixed"` emite un DEFAULT inválido para el enum nativo PG (etiqueta real `'FIXED'`), lo que rompe `create_all` sobre un esquema NUEVO (en `public` no se manifiesta porque la tabla ya existe) | **Ticket recomendado**: cambiar a `server_default="FIXED"` en ventana de mantenimiento. NO es regresión de este sprint |

**Pendiente operativo**: (a) seed inicial de tasas por gerencia post-deploy (§8.3 — tabla creada y vacía en dev); (b) consumo frontend del contrato §6.1 (nulos "no cortable" en modo slice, tooltip de `cogs_budget_trace` distinguiendo `source: "global"` para gobernanza §8.2, banners de `meta.warnings`); (c) mantener en UI el POST/PUT/DELETE de tasas restringido a roles de gerencia hasta que el backend tenga control por roles.

---

*Fin de la especificación — v1.2 (2026-09-04): consolidada a partir del HSpec del stakeholder, la verificación cuantitativa del esquema real del Sprint 1 (45 tablas; ausencia de `actual_incomes`; `credits` = cartera; 2 únicas plantillas de presupuesto income/expense), las decisiones D-1..D-6 de la sesión interactiva de definición y las erratas de implementación I-1..I-7 de §16. Estado: **implementada y verificada** (86/86 ACs).*
