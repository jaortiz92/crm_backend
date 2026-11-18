# Especificación Técnica: Commission Engine — Pilar 3 (Liquidación de comisiones por recaudo real)

| Campo | Valor |
| :--- | :--- |
| **Documento** | Spec Motor de Comisiones — Pilar 3 (soporte de pago de nómina comercial: recaudo real -> factura -> vendedor -> tasa) |
| **Modulo** | `budget` -> entidad `commission_rates` (unica tabla nueva, DDL via `create_all`) + servicio `BudgetEngine.get_commissions()` + endpoint `GET /budget/analytics/commissions` + CRUD `/budget/commission-rates` |
| **Version** | 1.0 |
| **Fecha** | 2026-09-07 |
| **Estado** | **Aprobada en sesion (2026-09-07) - pendiente de implementacion** |
| **Origen** | HSpec Pilar 3 (stakeholder) + sesion interactiva de definicion (Decisiones D-1..D-8; A-2/A-4/A-6/A-9/A-13/N-1 re-trabajados con stakeholder) |
| **Patron** | Liquidador de solo lectura (agregacion en memoria por ventana de pago) + entidad maestra de tasas clon exacto del patron `line_cost_rates` (02_09 D-2) |
| **Fuentes analizadas** | `app/models/budget/paymentLedger.py` (id_invoice/id_customer populated por ETL), `app/models/invoice.py`, `app/models/order.py`, `app/models/customerTrip.py`, `app/models/customer.py` (id_seller), `app/models/user.py` (first/last name), `app/models/credit.py` y `app/models/advance.py` (descartadas como puente: sin numero de documento), `app/utils/templates/budgetTemplates.py` (`_map_payment_ledger_relational_data`: regex de description + normalizacion FVFE, key menor, id_customer solo RC), `app/models/budget/lineCostRate.py` + `app/crud/budget/lineCostRate.py` + `app/api/budget/lineCostRate.py` + `app/schemas/budget/lineCostRate.py` (patron clonado), `app/core/constants.py` (TAX_RATE=0.19); verificacion de datos dev 2026-09-07: 116 filas CASH-in con id_invoice 0 % vinculadas, invoices 25 filas (desde FVFE1553), orders 197 con id_seller, customers 177 con id_seller, credits 0, advances 0 |

> **Correcciones frente al HSpec base** (hallazgos verificados en codigo + datos):
> 1. **`invoices` NO tiene `seller`.** La cadena real de atribucion es `payment_ledger.id_invoice -> invoices.id_order -> orders.id_seller -> users`. Fallback: `orders.id_customer_trip -> customer_trips.id_customer -> customers.id_seller` (D-2). El contrato usa `id_seller` (users.id_user); los nombres `seller`/`id_salesperson` del HSpec no existen.
> 2. **Fuente de tasas (el "[Punto a definir]" del HSpec):** tabla nueva `commission_rates`, clon exacto del patron `line_cost_rates` de 02_09: `commission_pct Numeric(5,2)`, `id_line` nullable (NULL = tasa global de ultimo recurso), vigencia `date_from/date_to`, `is_active`. Resolucion anclada a `payment_date` (D-1 de esta spec ve D-7).
> 3. **Base neta de IVA (D-1, re-trabajo de A-2 con stakeholder):** `comision = (recaudo / (1 + TAX_RATE)) x tasa`. La formula inicial del stakeholder `/(1-0.19)` se corrigio en sesion (inflaba 23.5 %). Se usa la constante `app.core.constants.TAX_RATE` (hoy 0.19), no el literal. Consecuencia de gobernanza: cada detalle del payload incluye `commission_base` (neto) porque con base neta el renglon ya NO cuadra `collected_amount x rate` a simple vista y esto es **soporte de pago**.
> 4. **El cruce recaudo->factura existe pero es heuristico y con cobertura 0 en dev:** el ETL de Recibos (02_07) parsea la `description` (regex con marcadores ordenados, normaliza `{n, "FVFE"+n}`, gana el primer candidato, `key` menor para cuotas). Hoy ninguna de las 116 filas CASH-in enlaza (las facturas citadas, p. ej. FVFE1461, no existen en las 25 filas CRM). Esto NO es bug de parser: es cobertura del ETL de facturas (§13 Dep-Cobertura) y hace a BR-44 (divulgacion de recaudo no atribuible) la regla mas importante del contrato en el corto plazo.
> 5. **`credits`/`advances` no pueden ser puente de atribucion:** `credits` no guarda el numero SIIGO del credito (solo id_invoice/term/valores), `advances` no tiene referencia de recibo; ambas en 0 filas. Las filas "PAGO CREDITO {num}" y "ANTICIPO" sin factura enlazable caen a la ruta de cliente (D-2) o a no-atribuible (BR-44).
> 6. **Sin clawback (D-6, re-trabajo de A-6):** en el negocio las NC se abonan a facturas futuras y no se devuelve dinero; toda fila `CASH in` aporta `+abs(payment_amount)`. Es identico a BR-22/23 de 02_10 (no confiar en el signo de captura). El payload no conoce renglones de comision negativos.
> 7. **Los demas gastos ligados a facturacion (envios, pasarela, etc.) NO entran (D-4):** ya tienen su ciclo completo sin liquidacion: se presupuestan en `budget_lines`, contabilidad los causa en `actual_expenses` y el P&L (02_09) los compara. La comision es el unico gasto que nadie mas puede desglosar por vendedor desde el recaudo. El motor **no auto-postea** la comision liquidada a `actual_expenses` (ruta contable intacta).

## 0. Registro de Decisiones (Decision Log)

| ID | Decision | Origen |
| :-- | :--- | :--- |
| **D-1** | **Base neta de IVA**: `commission_base = abs(payment_amount) / (1 + TAX_RATE)`; `commission_earned = commission_base x commission_pct / 100`. `TAX_RATE` se lee de `app.core.constants` (0.19 hoy). Divergencia consciente con el legado `project_cash_flow`, que MULTIPLICA presupuesto x (1+TAX) para proyectar salida bruta: son operaciones inversas con contextos distintos (plan neto -> caja bruta vs. caja bruta -> base neta); ninguna se unifica con la otra (no-regresion, §8.4). El payload incluye `commission_base` por detalle y `meta.tax_rate_used` para que la aritmetica del soporte de pago cierre fila por fila. | Re-trabajo A-2 (2026-09-07) |
| **D-2** | **Cadena de atribucion estricta y con orden fijo**: (1) con factura: `invoices.id_order -> orders.id_seller`; (2) pedido sin vendedor: `orders.id_customer_trip -> customers.id_seller`; (3) sin factura (anticipos) o cadena rota: `payment_ledger.id_customer -> customers.id_seller` (el ETL solo lo llena en filas RC con match exacto upper del `third_party`); (4) nada de lo anterior => **recaudo no-atribuible**: excluido de la liquidacion pero divulgado con conteo y monto en `summary` + `meta.warnings` (BR-44). Atencion: `customers.id_seller`, NUNCA `id_seller_origin` (vendedor de origen, no asignado). | A-3 + re-trabajo A-4 (2026-09-07) |
| **D-3** | **CRUD completo de `commission_rates` en este sprint** (opcion 1 del stakeholder): entidad con checklist de 4 puntos y endpoints espejo de `line_cost_rates` (GET lista con filtros `id_line`/`active_only`/`date`, GET by id, POST, PUT merge parcial, DELETE fisico con desactivacion como opcion de auditoria). Sin esto, ajustar una tasa exigiria un desarrollador con acceso SQL a produccion: inaceptable para dinero de nomina. | A-13 opcion 1 (2026-09-07) |
| **D-4** | **v1 = solo comisiones de vendedor.** Gastos tipo envio ya viven el ciclo presupuesto -> causa contable -> `actual_expenses` -> P&L; no necesitan liquidador. El engine no escribe en ninguna tabla (ruta comercial paralela a la contable); la divergencia comision-liquidada vs. comision-causada-por-contabilidad es hallazgo de revision humana, no del motor. El payload NO incluye gancho `category` (YAGNI: sin segundo caso de negocio escrito). | N-1 (2026-09-07) |
| **D-5** | **Periodo comercial 26->25 expuesto con prioridad**: `period=YYYY-MM` (opcional) deriva `[26 del mes anterior, 25 del mes]` server-side; `date_from/date_to` siguen para rangos ad-hoc; si llegan ambos, `period` manda con warning literal. Los bordes son inclusivos. El payload siempre ecoa la ventana efectiva + `meta.business_period` + `meta.period_source`. | A-9 opcion 1 (2026-09-07) |
| **D-6** | **Sin clawback**: normalizacion `+abs()` en la fuente para filas `CASH in` (como BR-23 en 02_10). Una fila `in` negativa se interpreta como error de captura, no como devolucion (las NC se abonan a facturas futuras y aparecen como recaudos positivos cuando ocurren). | Re-trabajo A-6 (2026-09-07) |
| **D-7** | **Tasa por linea con prorrata de recaudo**: cuando la factura tiene detalles, el `commission_base` neto se reparte por la participacion de cada detalle (`invoice_details.value_without_tax` -> `references -> brands -> lines`, mapeo de 02_09); cada tramo usa la tasa activa de su linea a la fecha del recaudo, con fallback global (`id_line` NULL). Factura sin detalles o tramo sin linea mapeada => balde "sin linea" con tasa global. El renglon reporta `commission_rate_applied` (tasa unica o effective-blend redondeada a 2) + `rate_details[]` con la traza completa. | A-1/A-5 aceptados + sesion |
**Supuestos aceptados sin cambios** (sesion 2026-09-07): A-5 prorrata por detalles (concretada en D-7); A-7 parametro `id_seller` + `seller_name` = "FIRST LAST" tal cual se almacena; A-8 cuotas de factura (key>1): el enlace del ETL usa la fila de key menor solo para resolver vendedor/linea, la comision es por recaudo y no por factura; A-10 payload = HSpec §5 literal + `meta` aditivo (misma politica de gobernanza que 02_09/02_10); A-11 sin tasa aplicable => 0.0 + warning (nunca HTTP error); A-12 redondeo a 2 dec por renglon y totales = suma de renglones redondeados (invariante de soporte de pago); A-14 motor 100 % read-only con JWT, cero colision de rutas; A-15 dependencia de cobertura del ETL de facturas (sin enlaces, la liquidacion cero es respuesta 200 valida, no error).

## 1. Objetivo del Proceso (*Process Objective*)

Dotar al `BudgetEngine` del metodo `get_commissions()` que produce la **liquidacion de comisiones de ventas sobre recaudos reales** (cash-basis, abandono definitivo de la causacion) para una ventana de pago `[date_from, date_to]` (normalmente el periodo comercial 26->25, D-5): recorre el libro de pagos, imputa cada recaudo a su factura (enlace `id_invoice` ya resuelto por el ETL 02_07), resuelve al vendedor con la cadena de D-2, descompone la base neta de IVA por linea de producto y aplica las tasas vigentes de `commission_rates`. El payload es **soporte de pago** para el cierre de nomina comercial: cada vendedor ve el detalle factura-por-factura de lo que genero. El motor **no escribe ni almacena resultados ni postea contablemente** (D-4).

**Fuera de alcance**: gastos variables distintos de comision de vendedor (envios, pasarelas: ruta contable intacta, D-4); clawbacks/devoluciones (D-6); liquidacion de anticipos SIN cliente identificable (caen a no-atribuibles, BR-44); auto-posteo a `actual_expenses` ni a ninguna tabla; comparacion comision-liquidada vs. comision-causada-por-contabilidad (extension documentada §13); comision por meta/bono escalonado (tasa fija o por linea, sin tramos); historizacion de asignaciones (punto-en-tiempo, BR-51); multi-moneda; frontend; pagos con `cash_flow IS NULL` o `NON_CASH_ADJUSTMENT` (BR-41).

## 2. Glosario

| Termino | Definicion |
| :--- | :--- |
| **Recaudo** | Fila del `payment_ledger` con `transaction_nature='CASH'` y `cash_flow='in'`: dinero que efectivamente entro al banco. |
| **Base neta** | `recaudo / (1 + TAX_RATE)`: el recaudo despojado del IVA (D-1). Es la base sobre la que se calcula la comision. |
| **Liquidacion** | Resultado del motor para una ventana: bloques por vendedor con el detalle de cada recaudo que comisiono. Soporte de pago, no documento contable. |
| **Periodo comercial** | Ventana de extraccion 26 del mes anterior -> 25 del mes actual (D-5). `period=YYYY-MM` nombra al periodo cuyo cierre cierra el dia 25. |
| **Atribucion** | Asignacion de un recaudo a un vendedor via la cadena de D-2. Atribucion de punto-en-tiempo: la asignacion ACTUAL en users/orders/customers, sin historial. |
| **Recaudo no-atribuible** | Fila `CASH in` de la ventana cuya cadena termina sin vendedor (tipico: anticipo sin `id_customer` matcheado o factura sin enlazar). Se excluye y se divulga (BR-44). |
| **Tasa de linea** | Fila de `commission_rates` con `id_line` poblada, vigente a la fecha del recaudo. |
| **Tasa global** | Fila de `commission_rates` con `id_line IS NULL`: ultimo recurso cuando no hay tasa de linea (o el tramo no tiene linea). |
| **Rate blend** | `commission_rate_applied` de un renglon con tramos de distinta tasa: `round(earned / base_neta x 100, 2)`; siempre conciliable con `rate_details[]`. |
| **Prorrata** | Reparto de la base neta de un renglon entre lineas segun la participacion de `value_without_tax` de los detalles de la factura (D-7). |
| **Favorability** | No aplica: la liquidacion no tiene signo de "mejora"; todo es aritmetico y positivo (D-6). |

## 3. Arquitectura y Puntos de Integracion

### 3.1 Diagrama de flujo

```text
 GET /budget/analytics/commissions?period|date_from&date_to[&id_seller&id_line]
        |  app/api/budget/analytics.py  (router ya montado, prefix /budget/analytics)
        |  valida: period YYYY-MM (o fechas), al menos una de las dos (E-CM-1),
        |          FK id_seller/id_line (E-CM-2), Deriva ventana [26,25] (D-5)
        |  Depends(get_current_user)
        v
 POST/PUT /budget/commission-rates ..... app/api/budget/commissionRate.py (nuevo, patron lineCostRate)
        |  BR-12/13 clonados: vigencia invertida 400, solape activo mismo grupo NULL-safe 400
        v
 BudgetEngine.get_commissions() ..................... app/services/budgetEngine.py (puro-aditivo)
   Paso 0  sin resolucion de presupuesto (a diferencia de 02_09/02_10: las tasas no son por presupuesto)
   Paso 1  Q1  Recaudos crudos: payment_ledger CASH in en ventana (sin GROUP BY: detalle por fila)  [1 query]
           Q2  Facturas enlazadas + pedidos + trips (lote por id_invoice)                           [1 query]
           Q3  customers.id_seller para trips y clientes del ledger (lote)                           [1 query]
           Q4  Detalles de factura con linea (value_without_tax, reference->brand->line)             [1 query]
           Q5  commission_rates activas (carga total: cientos de filas)                              [1 query]
   Paso 2  Ensamblar en Python: cadena de atribucion (D-2) -> base neta (D-1) -> prorrata (D-7)
           -> resolucion de tasa por tramo (BR-45) -> redondeo por renglon (BR-48)
   Paso 3  Filtros id_seller / id_line post-atribucion + divulgaciones de exclusiones
   Paso 4  summary + meta (filters, business_period, period_source, tax_rate_used, warnings)
   ** sin commit ** (100 % read-only, BR-49)
        v
 CommissionResponse { period, summary, commissions_by_seller[ {seller_name, total_collected,
                     total_commission, details[ {receipt_number, payment_date, invoice_number,
                     collected_amount, commission_base, commission_rate_applied,
                     rate_details[], commission_earned} ] } ], meta }
```

### 3.2 Archivos (12 puntos: entidad nueva con checklist de 4 puntos + motor + endpoint + smoke)

| # | Archivo | Accion | Detalle |
| :-- | :--- | :--- | :--- |
| 1 | `app/models/budget/commissionRate.py` | NUEVO | Tabla `commission_rates` (§4.1). Espejo exacto de `lineCostRate.py` con `commission_pct`. |
| 2 | `app/models/budget/__init__.py` | MOD | Registrar `CommissionRate` (mismo patron de re-export que `LineCostRate`). |
| 3 | `app/schemas/budget/commissionRate.py` | NUEVO | `CommissionRateBase/Create/Update/CommissionRate` clon de `lineCostRate.py` (Field ge=0 le=100, ConfigDict from_attributes). |
| 4 | `app/schemas/budget/budget.py` | MOD | Bloque `Commission*` de payload (§4.4) al final, junto a `PnL*`/`CashFlow*`. |
| 5 | `app/schemas/budget/__init__.py` + `app/schemas/__init__.py` | MOD | Imports explicitos (no `*`) de los 4 schemas de tasa + los 6 de payload. |
| 6 | `app/crud/budget/commissionRate.py` | NUEVO | Clon literal de `lineCostRate.py` CRUD (funciones get/get_by_id/create/update/delete con BR-12/13 espejados y literales de detalle compartidos). |
| 7 | `app/crud/budget/__init__.py` (+ `app/crud/__init__.py` segun el patron vigente) | MOD | Registrar el modulo (verbatim `from .commissionRate import *`). |
| 8 | `app/api/budget/commissionRate.py` | NUEVO | Router `/budget/commission-rates` espejo de `lineCostRate.py` (5 endpoints, docstrings analogos). |
| 9 | `app/api/__init__.py` y `app/main.py` | MOD | Import + `include_router` del nuevo router con el MISMO prefix/pattern que `lineCostRate` (unico archivo `main.py` tocado desde 02_07 en adelante; verificacion en implementacion del pattern exacto). |
| 10 | `app/services/budgetEngine.py` | MOD | + `_business_period()` + `get_commissions()` (§5), **puro-aditivo**. NO tocar `project_cash_flow`/`get_pnl`/`get_cash_flow`/`_cash_buckets` (AC-14). |
| 11 | `app/api/budget/analytics.py` | MOD | + ruta `GET /commissions` (§6.1). |
| 12 | `test/test_commission_engine_smoke.py` | NUEVO | Battery CMK de §11/§12. |

**DDL**: UNA tabla nueva (`commission_rates`) creada por `Base.metadata.create_all`; sin migraciones (convencion del proyecto). Orden de despliegue: crear tabla (deploy) -> sembrar tasas (CRUD) -> endpoint util. Las 6 tablas leidas (payment_ledger, invoices, orders, customer_trips, customers, users, + invoice_details/references/brands/lines para la prorrata) existen desde sprints previos.
## 4. Estructura de Datos

### 4.1 Tabla nueva `commission_rates` (unica DDL)

```python
class CommissionRate(Base):
    """Tasa de comision % por linea de producto, con vigencia (Pilar 3)."""
    __tablename__ = "commission_rates"

    id_commission_rate = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=True, index=True)
    rate_name = Column(String(120), nullable=True)
    commission_pct = Column(Numeric(5, 2), nullable=False)
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    is_active = Column(Boolean, server_default="True")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    line = relationship("Line", backref="commission_rates")
```

Sin restricciones SQL CHECK/UNIQUE de solape (decision heredada de 02_09 §4.1: la validacion vive en el CRUD, `id_line IS NULL` no es deduplicable con UNIQUE estandar). `id_line = NULL` = tasa global de ultimo recurso.

### 4.2 Campos-fonte verificados (verdad de campo por componente)

| Componente | Tabla | Campo | Fecha ancla | Reglas |
| :--- | :--- | :--- | :--- | :--- |
| Gatillo (recaudos) | `payment_ledger` | `payment_amount` (Numeric 15,2), `receipt_number`, `id_invoice`, `id_customer` | `payment_date` | `nature='CASH'` ∧ `cash_flow='in'`; aporte `+abs()` (D-6); **sin agregacion**: cada fila es un renglon de la liquidacion |
| Cadena vendedor | `invoices` -> `orders` -> (`customer_trips` -> `customers`) | `id_order`; `id_seller`; `id_customer_trip`; `id_seller` | — | Orden fijo de D-2; `users` solo aporta nombre (`first_name + ' ' + last_name`) |
| Cadena vendedor (sin factura) | `payment_ledger.id_customer` -> `customers` | `id_seller` | — | Ruta anticipos (D-2 paso 3); `id_customer` la llena el ETL solo en RC con match exacto upper |
| Prorrata de linea | `invoice_details` -> `references` -> `brands` -> `lines` | `value_without_tax` | — | Participacion = `value_without_tax / SUM(value_without_tax del detalle de la factura)`; detalle con `id_reference` NULL o sin linea mapeada => balde sin-linea (BR-46) |
| Tasas | `commission_rates` | `commission_pct` | vigencia vs. `payment_date` | `is_active` ∧ `date_from <= payment_date <= date_to`; linea concreta primero, global (NULL) despues (BR-45) |

**No usar** (trampas confirmadas): `payment_ledger.id_account_receivable` (el ETL lo deja NULL a proposito, documentado en `_map_payment_ledger_relational_data`: no es ruta de cruce); `accounts_receivable.paid_amount` (snapshot del estado de cuenta SIIGO, desfasa con Recibos.xlsx); `credits`/`advances` (sin numero de documento enlazable, 0 filas); `customers.id_seller_origin` (vendedor de origen != asignado); `users.active` como filtro (la obligacion de pago no desaparece si el usuario se desactiva, BR-51); `budget_lines.variable_rate`/`behavior_type='variable_sales'` (tasa PLANEADA de simulacion del legado, no fuente de liquidacion); `invoices.total_with_tax` para la prorrata (se prorratiza con `value_without_tax` del detalle, que es lo que uso 02_09); IVA literal 0.19 (usar constante).

### 4.3 Schemas Pydantic de la entidad (nuevo archivo `schemas/budget/commissionRate.py`, clon de lineCostRate)

`CommissionRateBase` (`id_line: Optional[int]`, `rate_name: Optional[str] max 120`, `commission_pct: float Field(ge=0, le=100)`, `date_from`, `date_to`, `is_active: Optional[bool]=True`), `CommissionRateCreate`, `CommissionRateUpdate` (todos opcionales, merge parcial), `CommissionRate` (+ `id_commission_rate`, timestamps). Verbatim del patron; unico rename `cogs_pct -> commission_pct`.

### 4.4 Schemas Pydantic del payload (adicion a `app/schemas/budget/budget.py`)

```python
class CommissionRateTrace(BaseModel):
    id_commission_rate: Optional[int] = None   # NULL cuando no habia tasa (pct=0)
    id_line: Optional[int] = None              # NULL = balde global / sin-linea
    line_name: Optional[str] = None
    commission_pct: float                      # 0.0 si no hubo tasa aplicable (A-11)
    base_net: float                            # porcion de la base neta en este tramo
    commission_earned: float                   # round(base_net * pct / 100, 2)


class CommissionDetailRow(BaseModel):
    id_payment_ledger: int                     # traza directa al libro (soporte de pago)
    receipt_number: str
    payment_date: date
    invoice_number: Optional[str] = None       # NULL en ruta anticipo (D-2 paso 3)
    collected_amount: float                    # bruto recaudado, SIEMPRE >= 0 (D-6)
    commission_base: float                     # neto de IVA: collected / (1 + TAX_RATE) (D-1)
    commission_rate_applied: float             # pct echo: tasa unica o blend (BR-47)
    rate_details: List[CommissionRateTrace]    # traza conciliable renglon a renglon
    commission_earned: float                   # = SUM(rate_details.commission_earned)


class CommissionSellerBlock(BaseModel):
    id_seller: int
    seller_name: str                           # users.first_name + ' ' + last_name
    total_collected: float                     # suma collected_amount de sus renglones
    total_commission: float                    # suma commission_earned de sus renglones
    details: List[CommissionDetailRow]


class CommissionSummary(BaseModel):
    total_collected_base: float                # Σ bruto de renglones ATRIBUIBLES (nombre HSpec)
    total_net_base: float                      # Σ commission_base (aditivo, gobernanza D-1)
    total_commissions_calculated: float        # Σ earned (invariante BR-48)
    total_unattributed_collected: float = 0.0  # Σ bruto no-atribuible (BR-44)
    unattributed_count: int = 0


class CommissionMeta(BaseModel):
    business_period: Optional[str] = None      # "2026-09" si la ventana deriva de periodo; else None
    period_source: str                         # "period_param" | "explicit_dates" (D-5)
    tax_rate_used: float                       # valor efectivo de TAX_RATE al resolver (D-1)
    filters: dict                              # eco de los 5 query params efectivos (BR-52)
    warnings: List[str] = []


class CommissionResponse(BaseModel):
    period: dict                               # {"from": iso, "to": iso} ventana EFECTIVA (HSpec literal)
    summary: CommissionSummary
    commissions_by_seller: List[CommissionSellerBlock]
    meta: CommissionMeta
```

> El top-level es el contrato del HSpec §5 (`period` + `summary` + `commissions_by_seller`) mas `meta` aditivo y campos aditivos dentro del renglon (`id_payment_ledger`, `commission_base`, `rate_details`): gobernanza de soporte de pago — la aritmetica debe cerrar para el que cobra y para el que paga. Colision de nombres verificada: no existe `Commission*` en los schemas actuales.

## 5. Especificacion Funcional — `BudgetEngine.get_commissions()`

### 5.1 Firma

```python
def get_commissions(
    self,
    date_from: date,                           # ventana ya resuelta (D-5 vive en el endpoint)
    date_to: date,
    id_seller: Optional[int] = None,           # filtro post-atribucion (HSpec §4)
    id_line: Optional[int] = None,             # corte por linea con prorrata (A-5/D-7)
    business_period: Optional[str] = None,     # etiqueta "YYYY-MM" para eco (None si fechas explicitas)
) -> Dict[str, Any]:
```

#### 5.1.1 Imports a adicionar en `budgetEngine.py`

```python
from app.models.budget import CommissionRate as CommissionRateModel   # modelo nuevo
# PaymentLedgerModel, InvoiceModel, OrderModel?, CustomerModel?, UserModel?,
# InvoiceDetailModel, ReferenceModel, BrandModel, LineModel: verificar bloque
# superior del archivo; get_pnl ya importa Invoice/InvoiceDetail/Reference/Brand;
# adicionar SOLO los que falten (Order/CustomerTrip/Customer/User/PaymentLedger
# ya importados — verificado 2026-09-07; Invoice NO estaba: get_pnl lo importa).
```

### 5.2 Helper de periodo comercial (D-5 — usado por el endpoint via el engine o modulo util)

```python
@staticmethod
def _business_period(period: str) -> tuple:
    """'2026-09' -> (date(2026, 8, 26), date(2026, 9, 25)). Bordes inclusivos.
    Enero deriva del diciembre del ano anterior. Valida formato YYYY-MM
    (E-CM-3 422 si no parsea)."""
    y, m = int(period[:4]), int(period[5:7])
    end = date(y, m, 25)
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return date(py, pm, 26), end
```

### 5.3 Queries exactas (SQLAlchemy legacy `db.query`, estilo del proyecto)

**Q1 — Recaudos crudos de la ventana** (BR-41; cada fila = renglon potencial):

```python
cash_rows = (self.db.query(
        PaymentLedgerModel.id_payment_ledger,
        PaymentLedgerModel.receipt_number,
        PaymentLedgerModel.payment_date,
        PaymentLedgerModel.payment_amount,
        PaymentLedgerModel.id_invoice,
        PaymentLedgerModel.id_customer)
     .filter(PaymentLedgerModel.transaction_nature == "CASH",
             PaymentLedgerModel.cash_flow == "in",          # jamac 'out' ni NULL (BR-41)
             PaymentLedgerModel.payment_date >= date_from,
             PaymentLedgerModel.payment_date <= date_to)
     .order_by(PaymentLedgerModel.payment_date,
               PaymentLedgerModel.id_payment_ledger)        # determinismo BR-52
     .all())
```

**Q2 — Cadena factura->pedido->trip en lote** (solo ids presentes):

```python
inv_ids = sorted({r.id_invoice for r in cash_rows if r.id_invoice})
invoice_rows = {}       # id_invoice -> (invoice_number, id_order, id_seller_order, id_customer_trip)
if inv_ids:
    rows = (self.db.query(
                InvoiceModel.id_invoice, InvoiceModel.invoice_number,
                OrderModel.id_seller, OrderModel.id_customer_trip)
            .join(OrderModel, InvoiceModel.id_order == OrderModel.id_order)
            .filter(InvoiceModel.id_invoice.in_(inv_ids)).all())
    # facturas SIN pedido (id_order NULL): segunda consulta ligera o LEFT JOIN;
    # se resuelven con invoice_number y cadena rota -> paso 3/4 de D-2
```

**Q3 — Vendedores por cliente en lote** (paso 2 y paso 3 de D-2):

```python
cust_ids = {via trips} | {r.id_customer for r in cash_rows if r.id_customer}
customer_seller = dict(self.db.query(
        CustomerModel.id_customer, CustomerModel.id_seller)
     .filter(CustomerModel.id_customer.in_(cust_ids),
             CustomerModel.id_seller.isnot(None)).all())
```

**Q4 — Detalles con linea de las facturas implicadas** (D-7; mapeo identico a 02_09 `reference->brand->line`):

```python
detail_rows = (self.db.query(
        InvoiceDetailModel.id_invoice,
        LineModel.id_line, LineModel.name,
        func.coalesce(func.sum(InvoiceDetailModel.value_without_tax), 0.0))
     .join(InvoiceModel, InvoiceDetailModel.id_invoice == InvoiceModel.id_invoice)
     .outerjoin(ReferenceModel, InvoiceDetailModel.id_reference == ReferenceModel.id_reference)
     .outerjoin(BrandModel, ReferenceModel.id_brand == BrandModel.id_brand)
     .outerjoin(LineModel, BrandModel.id_line == LineModel.id_line)
     .filter(InvoiceDetailModel.id_invoice.in_(inv_ids))   # solo si inv_ids no vacio
     .group_by(InvoiceDetailModel.id_invoice, LineModel.id_line, LineModel.name)
     .all())
# LEFT OUTER JOINs: el tramo cuyo detalle no tiene referencia (o cuya referencia
# no tiene linea/brand mapeada) conserva id_line=NULL y cae al balde "sin linea"
# (tasa global, BR-46) SIN peso perdido: la suma de tramos de una factura == la
# suma de value_without_tax de TODOS sus detalles; sin query extra.
```

**Q5 — Tasas activas** (carga total: es un maestro de cientos de filas max.):

```python
rates = (self.db.query(CommissionRateModel)
         .filter(CommissionRateModel.is_active.is_(True))
         .order_by(CommissionRateModel.id_commission_rate)   # desempate determinista BR-45
         .all())
rate_by_line_date = {...}   # (id_line, payment_date) -> primera fila vigente, menor id
global_rate_at = {...}      # id_line IS NULL -> primera vigente, menor id
```

### 5.4 Ensamblado (pseudocodigo exacto)

```python
TAX = 1 + TAX_RATE
for r in cash_rows:                            # Q1 ya ordenada
    gross = abs(float(r.payment_amount))       # D-6: SIEMPRE positivo
    net_base = gross / TAX                     # D-1 (precision completa en memoria)
    seller = resolve_seller(r)                 # cadena D-2; None => no-atribuible:
    if seller is None:
        unattributed_gross += gross; unattributed_count += 1; continue
    shares = decompose(net_base, r, q4_map)    # [(line, pct_of_net)] ; si no hay detalles
                                               # o no hay factura: un solo balde sin-linea
    if id_line is not None:
        shares = [s for s in shares if s.line == id_line]     # A-5: corte post-prorrata
        if not shares: continue                # y se cuenta en excluidos_por_corte
    for (line, share_net) in shares:
        rate = rate_by_line_date.get((line, r.payment_date)) or global_rate_at(r.payment_date)
        pct = float(rate.commission_pct) if rate else 0.0
        if rate is None: missing_rate_bucket.add(...)          # BR-45 -> warning agrupado
        earned_line = round(share_net * pct / 100, 2)          # BR-48: round POR TRAMO
    earned_row = round(sum(earned_line for tramos), 2)         # suma de tramos redondos
    row = { ..., commission_base=round(net_base, 2),
            commission_rate_applied=blend_unico_o_efectivo(),  # BR-47
            rate_details=[...], commission_earned=earned_row }
    if id_seller is not None and seller.id != id_seller: continue   # post-filtro
    buckets_by_seller[seller].append(row)
```

Orden de salida: `commissions_by_seller` por `id_seller` ASC; `details` por `(payment_date, id_payment_ledger)` ASC (BR-52). Un vendedor sin renglones despues de filtros NO aparece (no se emiten bloques vacios). Sellers se agrupan por `id_seller` resuelto (nombre se toma de `users`; 2 vendedores con igual nombre NO se fusionan: la clave es el id).
## 6. Contratos de API

### 6.1 `GET /budget/analytics/commissions`

```python
import re   # para el validador de period

@router.get("/commissions", response_model=CommissionResponse)
def get_commissions(
    period: Optional[str] = Query(None, description="Cierre de periodo comercial YYYY-MM (26->25, D-5)"),
    date_from: Optional[date] = Query(None, description="Ventana explicita (inclusive) sobre payment_date"),
    date_to: Optional[date] = Query(None, description="Ventana explicita (inclusive) sobre payment_date"),
    id_seller: Optional[int] = Query(None, description="Liquidar un vendedor especifico (users.id_user)"),
    id_line: Optional[int] = Query(None, description="Corte por linea de producto (prorrata de recaudo, D-7)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pilar 3 - Liquidacion de comisiones sobre recaudo real (cash-basis)."""
    if period is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise HTTPException(422, detail="period must be YYYY-MM")            # E-CM-3
    if period is None:
        if date_from is None or date_to is None:
            raise HTTPException(400, detail="period or both date_from and date_to are required")   # E-CM-1
        if date_from > date_to:
            raise HTTPException(400, detail="date_from must be on or before date_to")   # literal compartido E-1/02_09
    if id_seller is not None and crud.get_user_by_id(db, id_seller) is None:
        Exceptions.register_not_found("Seller", id_seller)                   # E-CM-2
    if id_line is not None and crud.get_line_by_id(db, id_line) is None:
        Exceptions.register_not_found("Line", id_line)                       # E-CM-2 (pattern 02_09)
    warnings_extra = []
    if period is not None and (date_from is not None or date_to is not None):
        warnings_extra.append("period and explicit dates both given; period wins")      # D-5 literal
    if period is not None:
        date_from, date_to = BudgetEngine._business_period(period)
        business_period = period
    else:
        business_period = None
    try:
        engine = BudgetEngine(db)
        result = engine.get_commissions(
            date_from=date_from, date_to=date_to, id_seller=id_seller,
            id_line=id_line, business_period=business_period)
        result["meta"]["warnings"] = warnings_extra + result["meta"]["warnings"]       # prelaciones de ventana antes que warnings de datos (BR-52)
        return result
    except HTTPException:
        raise
    except Exception as e:                                # patron analitica, E-CM-5
        raise HTTPException(500, detail=f"Error computing commissions: {e}")
```

> Si `crud.get_user_by_id` no existe con ese nombre, usar el CRUD de usuarios vigente (verificar en implementacion); la semantica es 404 si el `id_seller` no existe en `users` (activo o inactivo: BR-51 no filtra, pero el 404 solo protege de ids erroneos).

### 6.1.1 Respuesta 200 — ejemplo canonico (golden seed §11)

Peticion: `GET /budget/analytics/commissions?period=2026-09` (deriva `2026-08-26..2026-09-25`; tasas L1=3 % global=2 %):

```json
{
  "period": { "from": "2026-08-26", "to": "2026-09-25" },
  "summary": {
    "total_collected_base": 33320000.0,
    "total_net_base": 28000000.0,
    "total_commissions_calculated": 740000.0,
    "total_unattributed_collected": 500000.0,
    "unattributed_count": 1
  },
  "commissions_by_seller": [
    {
      "id_seller": 11, "seller_name": "ANA ROJO",
      "total_collected": 26180000.0, "total_commission": 620000.0,
      "details": [
        { "id_payment_ledger": 901, "receipt_number": "CMK1", "payment_date": "2026-08-26",
          "invoice_number": "FVFE9001", "collected_amount": 11900000.0,
          "commission_base": 10000000.0, "commission_rate_applied": 3.0,
          "rate_details": [ { "id_commission_rate": 51, "id_line": 71, "line_name": "CMK-LineA",
                               "commission_pct": 3.0, "base_net": 10000000.0, "commission_earned": 300000.0 } ],
          "commission_earned": 300000.0 },
        { "id_payment_ledger": 902, "receipt_number": "CMK2", "payment_date": "2026-09-10",
          "invoice_number": "FVFE9001", "collected_amount": 2380000.0,
          "commission_base": 2000000.0, "commission_rate_applied": 3.0,
          "rate_details": [ { "id_commission_rate": 51, "id_line": 71, "line_name": "CMK-LineA",
                               "commission_pct": 3.0, "base_net": 2000000.0, "commission_earned": 60000.0 } ],
          "commission_earned": 60000.0 },
        { "id_payment_ledger": 909, "receipt_number": "CMK9", "payment_date": "2026-09-15",
          "invoice_number": "FVFE9003", "collected_amount": 11900000.0,
          "commission_base": 10000000.0, "commission_rate_applied": 2.6,
          "rate_details": [
            { "id_commission_rate": 51, "id_line": 71, "line_name": "CMK-LineA",
              "commission_pct": 3.0, "base_net": 6000000.0, "commission_earned": 180000.0 },
            { "id_commission_rate": 52, "id_line": 72, "line_name": "CMK-LineB",
              "commission_pct": 2.0, "base_net": 4000000.0, "commission_earned": 80000.0 } ],
          "commission_earned": 260000.0 }
      ]
    },
    {
      "id_seller": 12, "seller_name": "BETO AZUL",
      "total_collected": 5950000.0, "total_commission": 100000.0,
      "details": [
        { "id_payment_ledger": 903, "receipt_number": "CMK3", "payment_date": "2026-09-25",
          "invoice_number": "FVFE9002", "collected_amount": 5950000.0,
          "commission_base": 5000000.0, "commission_rate_applied": 2.0,
          "rate_details": [ { "id_commission_rate": 53, "id_line": null, "line_name": null,
                               "commission_pct": 2.0, "base_net": 5000000.0, "commission_earned": 100000.0 } ],
          "commission_earned": 100000.0 }
      ]
    },
    {
      "id_seller": 13, "seller_name": "CINDA VERDE",
      "total_collected": 1190000.0, "total_commission": 20000.0,
      "details": [
        { "id_payment_ledger": 904, "receipt_number": "CMK4", "payment_date": "2026-09-01",
          "invoice_number": null, "collected_amount": 1190000.0,
          "commission_base": 1000000.0, "commission_rate_applied": 2.0,
          "rate_details": [ { "id_commission_rate": 53, "id_line": null, "line_name": null,
                               "commission_pct": 2.0, "base_net": 1000000.0, "commission_earned": 20000.0 } ],
          "commission_earned": 20000.0 }
      ]
    }
  ],
  "meta": {
    "business_period": "2026-09",
    "period_source": "period_param",
    "tax_rate_used": 0.19,
    "filters": { "period": "2026-09", "date_from": null, "date_to": null,
                 "id_seller": null, "id_line": null },
    "warnings": [
      "1 unattributed collection(s) totaling 500000.00 excluded from the settlement"
    ]
  }
}
```

Trazas del golden: CMK1 neto exacto `11.900.000 / 1,19 = 10.000.000` (D-1 probado con numero "limpio de IVA"); CMK2 sembrado como `-2.380.000` y aportando `+2.380.000` (D-6); CMK3 sin pedido-vendedor cae a `customers.id_seller` via trip (D-2 paso 2) y factura sin detalles cae a tasa global (D-7); CMK4 anticipo sin factura comisiona por cliente del ledger (D-2 paso 3); CMK9 prueba prorrata 60/40 con dos tasas y blend 2.60. **Quedan fuera por contrato**: CMK5 (no-atribuible, divulgada), CMK6 (`out`), CMK7 (`NON_CASH`), CMK8 (2026-07-31 fuera de ventana), CMK10 (2026-08-25) y CMK11 (2026-09-26) — los dos ultimos prueban la inclusividad del corte 26/25 (D-5). Los ids mostrados (11/12/13, 71/72, 51-53, 901+) son ilustrativos: el smoke los siembra con MAX+1 y assertion dinamica.

### 6.1.2 Tabla de modos sobre el mismo seed (invariantes de AC-8/AC-9)

| Peticion (desde el golden) | total_commissions_calculated | detalle |
| :--- | ---: | :--- |
| `period=2026-09` (default) | 740.000 | advertencia de no-atribuible |
| fechas explicitas `2026-08-26..2026-09-25` | 740.000 | JSON identico salvo `business_period: null` y `period_source: "explicit_dates"` |
| `period=2026-09&date_from=2026-01-01&date_to=2026-12-31` | 740.000 | ventana manda period + warning `"period and explicit dates both given; period wins"` |
| `period=2026-02` | 0.0 | ventana `2026-01-26..2026-02-25`, serie vacia valida (200) |
| `id_seller=S1` | 620.000 | solo bloque S1; `total_collected_base` 26.180.000; **la divulgacion no-atribuible se mantiene global** (BR-54) |
| `id_line=L1` | 540.000 | S1: 300k+60k+180k (CMK9 podado a su tramo L1 con 71 % proporcional de bruto: 7.140.000); CMK3/CMK4 excluidos sin linea => warning de corte con conteo |
| `id_line=L2` | 80.000 | solo el tramo L2 de CMK9 (4.000.000 neto al 2 %) |
| sin tasa global activa (PUT `is_active=false`) | 640.000 | CMK3/CMK4 pasan a pct 0.0 con warning agrupado `"No active commission rate for..."` (A-11); restaurar |

### 6.1.3 Diccionario de `meta`

| Campo | Regla |
| :--- | :--- |
| `business_period` | Etiqueta `YYYY-MM` si la ventana derivo del parametro `period`; `null` con fechas explicitas. |
| `period_source` | `"period_param"` o `"explicit_dates"` (eco de como se fijo la ventana, D-5). |
| `tax_rate_used` | Valor de `TAX_RATE` usado en la resolucion (auditoria de la formula D-1). |
| `filters` | Eco exacto de los **5** query params con defaults (incluidos `null`) — mismo patron de gobernanza que 02_09/02_10. |
| `warnings` | Orden estable (BR-52): warning de prelacion period>fechas (lo antepone el endpoint) -> no-atribuibles (BR-44) -> tasas faltantes (BR-45, agrupadas por grupo de resolucion) -> exclusiones del corte `id_line` -> desempates de solape de tasas. |

### 6.2 `CRUD /budget/commission-rates` (D-3 — contrato espejo de `/budget/line-cost-rates`)

| Metodo | Ruta | Notas |
| :--- | :--- | :--- |
| GET | `/` | filtros `id_line`, `active_only`, `date` (en vigencia), `skip/limit`; orden por `id_commission_rate` |
| GET | `/{id_commission_rate}` | 404 `CommissionRate` |
| POST | `/` | valida Line FK (404), vigencia invertida -> E-CR-1, solape activo mismo grupo (`id_line` NULL-safe) -> E-CR-2; `commission_pct` fuera de [0,100] -> 422 nativo Field |
| PUT | `/{id}` | merge parcial no-None; revalida BR-12/13 sobre el merge excluyendo la fila; 404 |
| DELETE | `/{id}` | fisico; la desactivacion audit-friendly es PUT `is_active=false` (mismo texto que lineCostRate) |

**Literales de error compartidos con 02_09** (no se inventa texto nuevo): `"date_to must be on or after date_from"` (E-CR-1) y `"Overlapping active rate for this line (or global) period; deactivate or adjust dates first"` (E-CR-2).

## 7. Contrato CRUD

- `commission_rates`: unico escritor de datos nuevos en esta spec (endpoint del §6.2). Sin endpoints de liquidacion (es GET-only, pilar analitico).
- Las 6+ tablas leidas no se tocan: `payment_ledger`/`invoices`/`orders`/`customer_trips`/`customers`/`users`/`invoice_details`/`references`/`brands`/`lines` siguen con sus CRUDs/ETLs existentes.
## 8. Requisitos No Funcionales

### 8.1 Rendimiento y escalabilidad

- 5-6 consultas por peticion (Q1..Q5, Q2/Q4 se omiten si no hay facturas enlazadas), ensamblado y prorrata en Python, cero window functions (coherente con D-6 de 02_10). Cardinalidades: recaudos `in` por ventana (decenas-semana, cientos-mes), facturas implicadas <= recaudos, tasas = maestro (cientos). Con 100 k filas en `payment_ledger`, latencia objetivo < 500 ms en dev Docker.
- Indices sugeridos (mismos heredados de 02_10 §8.1 + uno propio): `ix_payment_ledger_payment_date`, `ix_accounts_receivable_due_date`, `ix_accounts_payable_due_date`, y `ix_payment_ledger_id_invoice` (el motor filtra por ventana y sujeta por FK de enlace; hoy el modelo solo indexa `receipt_number`).
- Sin cache v1: la liquidacion debe reflejar la ultima carga del ETL. Sin paginacion: es un soporte de pago por periodo (acotado por la ventana; un cierre mensual son cientos de renglones).

### 8.2 Seguridad

- JWT obligatorio en todas las rutas (endpoint analitico + CRUD de tasas), coherente con `analytics.py`/`lineCostRate.py`.
- Superficie de entrada 100 % tipada: `date`/`int`/`str` con regex de formato; SQLAlchemy parametriza.
- **Gobernanza del dinero**: `commission_rates` es el maestro que fija cuanto se paga; cualquier cambio queda echo en el payload via `rate_details[].id_commission_rate` + `commission_pct` + `meta.tax_rate_used` + `meta.filters` => cada centavo liquidado es reproducible/auditable desde la propia peticion y la fila de tasa que lo genero. Restriccion por rol del POST/PUT/DELETE: misma recomendacion heredada de 02_09 §8.2 (aplicar cuando el sprint de frontend defina roles).
- Riesgo registrado: la atribucion es de punto-en-tiempo (BR-51) — si gerencia reasigna `customers.id_seller` o `orders.id_seller` retroactivamente, liquidaciones antiguas cambian de dueno. Mitigacion actual: los cierres se pagan pronto y el detalle incluye `id_payment_ledger` para re-ejecutar y comparar; la historizacion queda como extension documentada (§13).

### 8.3 Disponibilidad y operacion

- Lecturas sincronicas sin jobs; excepcion => 500 patron E-CM-5 sin escritura a medio hacer (BR-49). Datos mal capturados: corregir ETL/CRUD origen y re-llamar — el motor no cachea.
- Prerrequisito de valor real: ETL de Recibos al dia (02_07) **y catalogo de facturas CRM cubriendo los numeros citados** (hoy la cobertura del enlace es 0 % en dev, §13 Dep-Cobertura); tasas sembradas via CRUD (D-3). Con cero enlaces la respuesta es 200 con `total_unattributed_collected` = todo el CASH in de la ventana: la divulgacion (BR-44) hace visible el problema operativo sin romper el contrato.

### 8.4 Compatibilidad aguas abajo (regression surface)

- `project_cash_flow` + `GET /cash-flow-projection`, `get_pnl` + `GET /pnl`, `get_cash_flow` + `GET /cash-flow` **intactos** (guardia byte-a-byte AC-14: los dos smokes 02_09 y 02_10 deben seguir pasando). La divergencia de convencion IVA (legado multiplica, Pilar 3 divide, D-1) es esperable y documentada: no se unifican.
- Stubs `budget-vs-actual`/`tracking`/`clone-for-scenario` intactos. Cero consumidores `commission` en `crm_frontend/src` (verificar con grep en implementacion).
- Rutas nuevas sin colision: `/budget/analytics/commissions` y `/budget/commission-rates` (prefijo nuevo; `line-cost-rates` no choca por nombre de recurso).
- `app/main.py` se toca **solo** para `include_router` del nuevo CRUD (unico punto de registro que 02_10 no tuvo; verificar contra el registro de `line_cost_rates` y copiarlo literalmente).

## 9. Reglas de Negocio (continuan la serie de 02_10; BR-41..)

| ID | Regla | Fuente |
| :-- | :--- | :--- |
| BR-41 | Unico gatillo: `payment_ledger` con `transaction_nature='CASH'` ∧ `cash_flow='in'` en la ventana sobre `payment_date`; `out`, NULL y `NON_CASH_ADJUSTMENT` excluidos. Cada fila = un renglon (sin agregacion) | HSpec §2, D-6 |
| BR-42 | Base neta: `commission_base = abs(payment_amount) / (1 + TAX_RATE)` con `TAX_RATE` de `app.core.constants`; `meta.tax_rate_used` ecoa el valor; la normalizacion `abs()` aplica en la fuente (una fila `in` negativa es error de captura, no devolucion) | **D-1/D-6** |
| BR-43 | Cadena de atribucion con orden fijo y parada al primer hit: `orders.id_seller` -> (`order.trip.customer`).`customers.id_seller` -> (`ledger.id_customer`).`customers.id_seller`; nunca `id_seller_origin` | **D-2** |
| BR-44 | Recaudo sin vendedor al final de la cadena => EXCLUIDO del calculo pero DIVULGADO: `summary.total_unattributed_collected` + `unattributed_count` + warning con conteo y monto; jamas silencioso | **D-2**, A-4 |
| BR-45 | Tasa: `is_active` ∧ `date_from <= payment_date <= date_to`; prioridad tasa de la linea del tramo, fallback global (`id_line IS NULL`); multiplices vigentes del mismo grupo => menor `id_commission_rate` + warning de desempate; ninguna => pct 0.0 con warning agrupado (200, no error) | **D-7**, A-1/A-11 |
| BR-46 | Prorrata: el `commission_base` del renglon se reparte entre lineas por `value_without_tax` de los detalles de SU factura (mapeo `reference->brand->line` de 02_09); detalles sin referencia/sin linea => balde sin-linea (tasa global); factura sin ningun detalle => renglon completo al balde sin-linea; suma de baldes == `commission_base` (sin peso perdido) | **D-7** |
| BR-47 | `commission_rate_applied`: con un solo tramo, el `commission_pct` de la tasa; con varios, blend efectivo `round(earned / commission_base x 100, 2)`. `rate_details[]` SIEMPRE presente y conciliable (Σ tramos = renglon) | **D-7** |
| BR-48 | Invariante de soporte de pago: redondeo a 2 decimales POR TRAMO; `commission_earned` = Σ tramos; `total_commission` = Σ renglones; `total_commissions_calculated` = Σ vendedores — todas las sumas exactas sobre valores ya redondeados (sin re-agregacion en crudo) | A-12 |
| BR-49 | Motor 100 % lectura: ningun add/flush/commit/delete/update en `get_commissions`/`_business_period`; el UNICO escritor de `commission_rates` es su CRUD (§6.2) | D-4, A-14 |
| BR-50 | Top-level del payload = HSpec §5 literal (`period`/`summary`/`commissions_by_seller`) + `meta` aditivo + campos aditivos de renglon (`id_payment_ledger`, `commission_base`, `rate_details`) | A-10 |
| BR-51 | Atribucion de punto-en-tiempo: se usa la asignacion actual de `users`/`orders`/`customers` (sin SCD); `users.active` NO filtra (deuda de pago persiste tras desactivar) | Sesion, §8.2 |
| BR-52 | Determinismo: Q1 ordena `(payment_date, id_payment_ledger)`; vendedores por `id_seller` ASC; detalles en orden de Q1; warnings en el orden fijo de §6.1.3; `meta.filters` ecoa los 5 params con defaults | §5.4 |
| BR-53 | Periodo comercial: `[26 mes N-1, 25 mes N]` inclusivo; enero deriva de diciembre del ano anterior; `period` con formato `YYYY-MM` (422 E-CM-3); si `period` y fechas llegan juntas, `period` manda + warning literal | **D-5** |
| BR-54 | Filtros: `id_seller` poda DESPUES de atribuir (la divulgacion de no-atribuibles se mantiene global); `id_line` poda tramos de la prorrata y excluye renglones sin participacion en esa linea, con warning de conteo; vendedores sin renglones tras poda desaparecen del payload (sin bloques vacios) | A-5, sesion |

## 10. Catalogo de Errores

| # | Codigo | Trigger | `detail` |
| :-- | :--- | :--- | :--- |
| E-CM-1 | 400 | Sin `period` y sin ambas fechas, o `date_from > date_to` | `"period or both date_from and date_to are required"` / `"date_from must be on or before date_to"` (segundo literal compartido con E-1/02_09 y E-CF-1/02_10) |
| E-CM-2 | 404 | `id_seller` inexistente en `users` o `id_line` inexistente | patron `Exceptions.register_not_found("Seller"/"Line", id)` |
| E-CM-3 | 422 | `period` no `YYYY-MM`, fechas mal formateadas, `commission_pct` fuera de [0,100] (CRUD) | nativo FastAPI/regex/Field |
| E-CM-4 | 401/403 | Sin JWT | estandar FastAPI |
| E-CM-5 | 500 | Cualquier otra excepcion BD/parseo | `"Error computing commissions: {e}"` (patron analitica) |
| E-CR-1 | 400 | Vigencia invertida en POST/PUT de tasa | `"date_to must be on or after date_from"` (literal compartido 02_09) |
| E-CR-2 | 400 | Solape de tasa activa mismo grupo (`id_line` NULL-safe) | `"Overlapping active rate for this line (or global) period; deactivate or adjust dates first"` (literal compartido 02_09) |

Sin enlaces de facturas, sin tasas, o ventana sin recaudos **no son errores**: 200 con liquidacion cero y warnings (filosofia E-6/02_09 y §10/02_10).

## 11. Criterios de Aceptacion (golden seed deterministico)

**Seed de prueba** (BD dev con backend :8003; marcador `CMK`; cadena de FK auto-contenta sembrada por SQL directo con MAX+1 — leccion de secuencias del ETL): 3 usuarios vendedor (`ANA ROJO`/`BETO AZUL`/`CINDA VERDE`, documentos unicos 990000x), 2 lineas `CMK-LineA/B` con su brand+reference, 2 customers (`CMK-C2` vendedor S2, `CMK-C3` vendedor S3), trips/orders correspondientes, 3 facturas: FVFE9001 (pedido S1, detalle 100 % LineA), FVFE9002 (pedido SIN `id_seller`, trip->CMK-C2, cero detalles), FVFE9003 (pedido S1, detalles LineA 6.000.000 / LineB 4.000.000 `value_without_tax`); 12 filas `payment_ledger` (recibos `CMK1..CMK12`) segun las trazas de §6.1.1 — CMK12 es la fila `in` `-2.380.000` ya incluida como CMK2; las tasas se crean **via el API** (POST `/budget/commission-rates`): LineA 3 %, global 2 %, vigencia 2026-01-01..2026-12-31 (prueba D-3 sin romper el golden). Ventana golden: `period=2026-09` => `[2026-08-26, 2026-09-25]`. Cuarentena: otras tasas activas 2026 preexistentes en la tabla (deben venir en 0 por tabla nueva, pero el smoke las desactiva/restaura por higiene; `finally` con restore y limpieza total `CMK%`).

| AC | Criterio |
| :-- | :--- |
| **AC-1** (integracion/DDL) | Tabla `commission_rates` creada por `create_all`; `from app.schemas import CommissionResponse` importa; OpenAPI lista `/budget/analytics/commissions` con `$ref CommissionResponse`, `/budget/commission-rates` (5 rutas) y los schemas `Commission*` en components (patrón I-6). |
| **AC-2** (golden) | `?period=2026-09` reproduce EXACTAMENTE el JSON de §6.1.1 (ids dinamicos comparados contra los sembrados): 3 bloques, summary 33.320.000/28.000.000/740.000/500.000/1, verificacion SQL cruzada ±0.01 de cada escalar (§12.2). |
| **AC-3** (D-1) | CMK1: `collected_amount=11.900.000`, `commission_base=10.000.000` exactos, `earned=300.000`; `meta.tax_rate_used == 0.19` == constante del codigo. |
| **AC-4** (D-2) | CMK3 atribuye S2 por trip->customer (el pedido no tiene `id_seller`); CMK4 atribuye S3 por `ledger.id_customer` con `invoice_number: null`; una cuarta fila sembrada CMK12 (factura sin `id_order` + `id_customer` del ledger matcheado) confirma el paso 3 con factura presente. |
| **AC-5** (D-6/BR-42) | CMK2 sembrada `-2.380.000` aparece como `collected_amount=+2.380.000` y comisiona `+60.000` (normalizacion demostrada con dato adverso). |
| **AC-6** (BR-41) | CMK6 (`out`) y CMK7 (`NON_CASH`) no afectan ningun total (asserts del golden). |
| **AC-7** (BR-44) | CMK5 (500.000) en `total_unattributed_collected` con `unattributed_count=1` + warning literal; ningun vendedor la recibe. |
| **AC-8** (D-5/BR-53) | CMK10 (25-08) y CMK11 (26-09) fuera; fechas explicitas == misma ventana == JSON identico salvo `business_period`/`period_source`; `period=2026-02` => `[2026-01-26, 2026-02-25]` echo; `period=2026-01` deriva de `2025-12-26` (cruce de ano); `period + fechas` => warning de prelacion. |
| **AC-9** (BR-54) | `id_seller=S1`: solo bloque S1 (620.000) y divulgacion global intacta; `id_line=L1`: 540.000 con CMK9 podado (base 6.000.000, bruto echo 7.140.000) y warning de exclusion (CMK3/CMK4); `id_line=L2`: 80.000. |
| **AC-10** (BR-45/A-11) | PUT global `is_active=false` => CMK3/CMK4 con pct 0.0, total 640.000, warning agrupado "No active commission rate...", HTTP 200; restaurar. Dos tasas LineA vigentes solapadas (sembrar via SQL saltando el CRUD) => gana menor id + warning de desempate; limpiar. |
| **AC-11** (BR-48) | En TODAS las respuestas capturadas: `total_commissions_calculated == Σ total_commission == Σ commission_earned == Σ Σ rate_details.commission_earned` (triple cuadre exacto) y `Σ collected (atribuidos) == total_collected_base`. |
| **AC-12** (BR-49) | Conteos identicos antes/despues de 5 llamadas en las 7 tablas leidas + `commission_rates` (el CRUD escribe solo fuera de esta fase). |
| **AC-13** (D-3) | Validaciones del CRUD: POST 200; solape mismo grupo 400 E-CR-2 exacto; `commission_pct=101` 422; vigencia invertida 400 E-CR-1; PUT merge parcial; PUT `is_active=false` saca de resolucion; DELETE fisico. |
| **AC-14** (regresion) | `cash-flow-projection?budget_year=2026` y `pnl` y `cash-flow` byte-a-byte estables; `test_pnl_engine_smoke.py` 208/208 y `test_cash_flow_engine_smoke.py` 177/177 al final (guardia cruzada: las tres conviven en `budgetEngine.py`); `git diff` solo-aditivo en `get_pnl`/`project_cash_flow`/`get_cash_flow`. |
| **AC-15** (errores) | E-CM-1 ambos literales; E-CM-2 `id_seller=999999`/`id_line=999999` 404; E-CM-3 `period=2026-13` 422; E-CM-4 sin token 401/403 en `/commissions` y en el CRUD. |
| **AC-16** (idempotencia) | Post-ejecucion: cero filas `CMK%` en las 7 tablas + cero `commission_rates` sembradas + cuarentenas restauradas + conteos == snapshot inicial. |

## 12. Estrategia de Pruebas (se extiende el patron de 02_09/02_10)

1. **Smoke dedicado**: `test/test_commission_engine_smoke.py`, clon de la arquitectura (fase 0 pre-clean `CMK%`, login JWT, seed SQL MAX+1 con cadena de FK completa, tasas via POST API, reporte `N/M`, restore en `finally`).
2. **Determinismo estructural**: a diferencia de 02_10 no hace falta `cutoff_date` — el motor no tiene dependencia de "hoy" (las anclas son `payment_date` y vigencia de tasas dentro de la ventana); toda la battery es estable sin relojes falsos.
3. **Verificacion SQL cruzada**: cada escalar del golden contra su propia fuente (Σ bruto atribuido, Σ neto, tramos por linea, no-atribuibles) ±0.01.
4. **Matriz de modos**: §6.1.2 (8 peticiones) + AC-10 con mutacion temporal de tasas restaurada.
5. **Regresion cruzada**: AC-14 ejecuta los dos smokes anteriores al final; los tres pilares comparten `budgetEngine.py`.

## 13. Supuestos y Dependencias

- **Dep-Cobertura (la critica)**: con `invoices` cubriendo solo 25 facturas locales, el enlace del ETL no aterriza NINGUN recaudo real (verificado: 116/116 `id_invoice` NULL). La operatividad del Pilar 3 depende de sincronizar el catalogo de facturas (import SIIGO de facturas de venta con el mismo `invoice_number`/key). Mientras tanto el endpoint responde liquidaciones validas con `total_unattributed_collected` creciente: es el termometro visible de la dependencia, no un bug.
- **Dep-BD**: Postgres 16; UNA tabla nueva via `create_all`; checklist de 4 puntos aplica (a diferencia de 02_10). Despliegue: deploy -> crear tasas por CRUD -> primer cierre.
- **IVA uniforme (D-1)**: la formula asume que TODO recaudo corresponde a facturas gravadas al `TAX_RATE` vigente. Si el catalogo tuviera facturas al 5 %/exentas, la correccion es derivar el factor por factura (`total_without_tax / total_with_tax`) en lugar de la constante — queda registrado como unica mutacion posible de la formula; el contrato NO cambia de forma.
- **Mantenimiento de tasas**: owner sugerido gerencia comercial via frontend (pendiente sprint UI); hasta entonces, soporte tecnico via API con JWT.
- **Sin auto-posteo contable (D-4)**: la divergencia comision-liquidada vs. causada-en-`actual_expenses` es insumo de revision humana; un reporte `commissions-vs-accounting` (mismo patron budget-vs-actual) es la extension natural futura, no parte de esta spec.
- **Atribucion sin historial (BR-51)**: reasignaciones retroactivas de vendedor cambian cierres pasados; la solucion real (columna `id_seller` en facturas capturada por el ETL de origen, o SCD) es sprint futuro con decision de negocio.
- **Nomenclatura**: el HSpec pedía `GET /budget/analytics/commissions` — se adopta literal (hermana de `/pnl` y `/cash-flow`). El CRUD usa el patron de recurso plural de `line-cost-rates`: `/budget/commission-rates`.
- **`crud.get_user_by_id`**: verificar en implementacion el CRUD de usuarios vigente (si no existe con ese nombre, adicionar la consulta directa en el endpoint o reusar `get_user` segun el nombre actual — sin tocar el CRUD de users).

## 14. Matriz de Trazabilidad (HSpec -> especificacion)

| HSpec | Estado | Donde |
| :--- | :--- | :--- |
| §1 Objetivo (cash-basis, cierre de nomina) | Aceptado | §1, BR-41 |
| §2 Gatillo (ledger CASH in) | Aceptado | §4.2, BR-41 |
| §2 Origen de la venta (`invoices.seller`) | **Corregido**: no existe; cadena de atribucion | Preámbulo 1, D-2, BR-43 |
| §2 Tasas "[a definir]" | **Definido**: `commission_rates` patron line_cost_rates | D-3, §4.1, §6.2 |
| §3 Cruce pago->documento | Existe via ETL (heuristico, cobertura 0 en dev); sin doble fuente | Preámbulo 4/5, §13 Dep-Cobertura |
| §3.4 Formula `recaudo x tasa` | **Re-trabajado con stakeholder**: base neta `/ (1+TAX_RATE)` | D-1, BR-42 |
| §3 nota pago parcial | Aceptado: la comision es por renglon de recaudo (cada pago parcial liquida su parte) | §5.4, BR-41 |
| §4 Parametros (`seller`/`id_salesperson`) | **Corregido**: `id_seller` (users.id_user) | A-7, §6.1 |
| §4 Filtro `id_line` | Aceptado con prorrata y podado post-cálculo | D-7, BR-46, BR-54, AC-9 |
| §5 Payload | Aceptado literal + `meta` aditivo + campos de trazabilidad | §4.4, BR-50 |
| (implicito HSpec) cierre mensual | **Refinado**: periodo comercial 26->25 con `period` param | D-5, BR-53, AC-8 |

## 15. Checklist de Implementacion (orden recomendado)

1. [ ] Entidad `commission_rates`: modelo + `__init__` de models (puntos 1-2 del §3.2).
2. [ ] Schemas de entidad (punto 3) + schemas de payload en `budget.py` (punto 4) + registros en ambos `__init__.py` (punto 5).
3. [ ] CRUD de tasas (punto 6) con literales compartidos 02_09 + registros (punto 7).
4. [ ] API `/budget/commission-rates` (punto 8) + registro en `api/__init__` y `main.py` (punto 9) ⇒ AC-13 parcial.
5. [ ] `BudgetEngine._business_period()` + `get_commissions()` Q1..Q5 + ensamblado (punto 10, puro-aditivo; `git diff` confirma `get_pnl`/`get_cash_flow`/`project_cash_flow` intactos).
6. [ ] Endpoint `GET /commissions` en `analytics.py` (punto 11) con validaciones E-CM-1/2/3.
7. [ ] Smoke `test/test_commission_engine_smoke.py` (AC-1..AC-16, §12) ⇒ cerrar verificacion.
8. [ ] Ejecutar ademas `test_pnl_engine_smoke.py` (208/208) y `test_cash_flow_engine_smoke.py` (177/177) — guardia cruzada AC-14.
9. [ ] Comunicar el contrato §6.1 al frontend (curva = P&L, caja = Pilar 2, liquidacion = soporte de pago por vendedor con banner de no-atribuibles y de tasas faltantes; calendario de periodos 26->25).

---

*Fin de la especificacion — v1.0 (2026-09-07): consolidada desde el HSpec Pilar 3 del stakeholder (comisiones por recaudo), la verificacion de verdad de campo (cadena de atribucion real, enlace ETL heuristico con cobertura 0 en dev, `credits`/`advances` descartados como puente, patron `line_cost_rates` clonado), y las decisiones D-1..D-8 de la sesion interactiva (base neta de IVA corregida en sesion, periodo comercial 26->25, CRUD de tasas incluido, v1 sin clawback ni otros gastos variables). Estado: **aprobada (2026-09-07) — pendiente de implementacion**.*