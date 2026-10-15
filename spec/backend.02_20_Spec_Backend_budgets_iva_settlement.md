# Spec Backend: IVA — flag por renglón de gasto, eventos de IVA y liquidación con calendario

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S10-IVA` |
| **Spec counterpart** | FE: `frontend.03_14` (FE-S14-IVA) |
| **Bases** | BE-S9 (`02_19`, streams proveedor/internación), BE-S8 (`02_18`), BE-S6 (`02_16`, patrón ALTER manual), BE-S4 (`02_12`, planning), `02_02` §6 (bases de gastos variables) |
| **Tablas nuevas** | 1: `iva_periods` (auto-creada por `create_all`) |
| **DDL manual requerido** | SI: `ALTER TABLE budget_lines ADD COLUMN IF NOT EXISTS has_iva BOOLEAN;` (§10 — `create_all` NUNCA altera tablas existentes; patrón `include_carryover` de BE-S6) |
| **Convenciones** | T-03 `db.query`, T-05 un solo commit, camelCase, checklist 4-puntos para `IvaPeriod`, pila JWT, montos Float con round(2) en respuesta, cero enums nuevos (cero ALTER TYPE) |
| **Fecha** | 2026-09-22 (sesión spec-definer con stakeholder) |

---

## 0. Problema

El flujo de planeación modela solo valores NETOS: un ingreso presupuestado de 10.000.000 se
recauda en 11.900.000 y la cuadrícula muestra 10.000.000; los gastos con IVA se pagan netos;
las compras nunca pagan el IVA de importación (19 % sobre el componente proveedor) ni el IVA
de internación (19 % sobre cada cuota de internación); y no existe una liquidación con
calendario de vencimientos (p. ej. 21-may vence el bimestre ene-feb) donde el valor a pagar
sea `IVA generado − IVA descontable`, con arrastre de saldos a favor al período siguiente.

## 1. Modelo conceptual

```
T = TAX_RATE = 0.19 (app/core/constants.py — única fuente de la tasa, NO configurable)

GENERADO (por recaudar):   ingreso_fijo(payment_date)                     × T
DESCONTABLE (por pagar):   gasto_fijo(con flag IVA)                        × T
                           gasto_variable(con flag IVA) sobre su base       × T
                           compra: IVA-importación = CostoProveedor         × T  (de contado en budget_date)
                           compra: IVA-internación = cuota_internación_k    × T  (junto a cada cuota)

LIQUIDACIÓN por período p (orden period_no, base CAJA — el evento cae en el período de la
FECHA DEL MOVIMIENTO, no de la causación):

  base_p        = generado_p − descontable_p − saldo_favor_{p-1}
  pago_p        = max(0, base_p)          → se paga en payment_due_date_p
  saldo_favor_p = max(0, −base_p)         → arrastra al período siguiente sin límite
```

### 1.1 Registro de decisiones del stakeholder (sesión 2026-09-22 — trazabilidad)

| ID | Decisión | Origen |
|---|---|---|
| D-S10-1 | Tasa global fija 19 % (`TAX_RATE`) para TODO el IVA del sistema: sin tasas por categoría ni por línea | Q1 + Q4 opción 1 |
| D-S10-2 | La categoría de IVA de un GASTO es **por renglón**: columna `Con IVA` (Si/No) que YA EXISTE en la plantilla real de SIIGO (fila 8, col 11; hoy el ETL la ignora). NO por CECO, NO por Línea | Supuesto 4 corregido |
| D-S10-3 | Compatibilidad: filas sin flag (cargas antiguas, columna ausente, celda vacía) se tratan como **CON IVA**; el stakeholder corregirá manualmente lo que no | Q2 |
| D-S10-4 | El flag es editable por fila en el line manager (agregar/quitar el "Con IVA") ⇒ ÚNICO dato de IVA materializado: columna booleana nullable `budget_lines.has_iva` (NULL ≡ True). Los MONTOS de IVA nunca se materializan: siempre derivados | Q3 + A13 heredado de BE-S9 |
| D-S10-5 | Ingresos: SIEMPRE gravados (el flag `has_iva` en una línea INCOME se ignora en el cálculo); recaudo bruto = neto × 1.19 | A1/A2 aprobados |
| D-S10-6 | Compra — IVA de importación = T × CostoProveedor (`Total/(1+%int)`): UN solo evento de contado en `budget_date` (fecha de compra), dentro de la corriente de pago a proveedores | A5 + Q6 lectura A |
| D-S10-7 | Compra — IVA de internación = T × cada cuota del stream de internación: se paga y se descuenta JUNTO con cada cuota ("como en los gastos, al pagar") | A5 v2 |
| D-S10-8 | Degradación: Línea sin `%int` o CECO sin Línea ⇒ CostoProveedor = Total ⇒ IVA-importación = T × Total; IVA-internación = 0 (cero stream int). Sin advertencia bloqueante | Q4 opción 1 |
| D-S10-9 | **[SUPERADA 2026-10-14]** Base de liquidación = **CAUSACIÓN**: cada evento cae en el período que cubre `budget_date` de la línea (generado y descontable). Antes era base de caja (recaudo/pago). | Q5 |
| D-S10-10 | Calendario configurable por año: tabla `iva_periods` (rango de fechas + vencimiento) — cubre el patrón bimestral del stakeholder (ene-feb vence 21-may) sin hardcodear reglas DIAN | A6 |
| D-S10-11 | Sin aplicación manual del saldo: arrastre automático ilimitado; saldo a favor no se paga ni se devuelve ni se compensa en v1 | A8/A9 |
| D-S10-12 | v1 = liquidación PROYECTADA sobre las líneas del escenario; NO toca carryover, NO toca `budgetEngine` (pilares 1/2/3) ni `project_cash_flow` legacy; conciliación contra IVA real = PQ | A7/A10/A15 |

## 2. Alcance

**Incluye:** (1) columna `budget_lines.has_iva` + mapeo ETL de `Con IVA`; (2) flag editable
en line manager (`POST/PUT /budget/planning/line`); (3) catálogo `iva_periods` CRUD REST;
(4) motor de eventos de IVA + liquidación `GET /budget/iva/settlement/{id_budget}` (pura
derivación de lectura); (5) smoke.

**Excluye (v1, → §8 PQ):** ventas 0 %/excluidas; liquidación de arrastres N−1; liquidación
de datos reales (facturas/auxiliares); ICA/retefuente/arancel; AP automáticos al vencimiento;
devoluciones/compensaciones; tasas distintas de 19 %; override de tasa por renglón; cambios
en `budgetEngine.get_pnl/get_cash_flow/get_commissions/project_cash_flow` y en el carryover.
---

## 3. Modelo de datos

### 3.1 `budget_lines.has_iva` (columna nueva — la ÚNICA mutación de esquema en tabla existente)

```python
# app/models/budget/budgetLine.py
has_iva = Column(Boolean, nullable=True)   # NULL ≡ True (D-S10-3). Solo significativo
                                           # para line_type=EXPENSE (D-S10-5: INCOME ignora;
                                           # PURCHASE siempre gravado en ambos streams).
```

- Sin backfill: NULL se interpreta como True en la derivación (§4); cero UPDATEs de datos.
- DDL de despliegue en §10. `create_all` NO la añade (tabla existente).

### 3.2 `iva_periods` — calendario de liquidación por año (`app/models/budget/ivaPeriod.py`)

```python
class IvaPeriod(Base):
    """Calendario de vencimientos de liquidación de IVA de un año fiscal."""
    __tablename__ = "iva_periods"

    id_iva_period = Column(Integer, primary_key=True, index=True)
    period_year = Column(Integer, nullable=False, index=True)   # año fiscal
    period_no = Column(Integer, nullable=False)                 # ordinal 1..N (bimestres: 1..6)
    date_from = Column(Date, nullable=False)                    # inicio del rango de caja
    date_to = Column(Date, nullable=False)                      # fin del rango (inclusive)
    payment_due_date = Column(Date, nullable=False)             # vencimiento de pago (p. ej. 2027-05-21)
    description = Column(String(120), nullable=True)

    __table_args__ = (UniqueConstraint("period_year", "period_no", name="uq_iva_periods_year_no"),)
```

- Tabla NUEVA ⇒ la crea `create_all` sin DDL manual (NFR-BE9-5 extendido).
- Rangos entre períodos NO se validan ni se solapan-regresan: un evento busca el PRIMER
  período que lo cubre por `period_no` ASC; los huegos-causa del bucket `unassigned` (§4.4)
  y los solapamientos degradan determinísticamente. Unicidad dura: solo (año, número).
- Sin vigencia multi-escenario: el calendario es POR AÑO, compañía única (ASM: no hay
  multi-compañía en el CRM). Escenario base y what-if del mismo año comparten calendario.
- Checklist 4-puntos de registro espejo de `lineInternmentRate` (models→schemas→crud→api;
  `app/main.py` NO cambia).

## 4. Derivación de eventos y liquidación (`app/services/budgetIvaEngine.py` — NUEVO)

Clase `BudgetIvaEngine(db: Session)` — capa de agregación PURA de lectura (patrón BR-19/
BR-32/BR-CO-04): cero `add/flush/commit/delete`. `T = TAX_RATE`.

### 4.1 Hechos de entrada (queries Q1–Q6, economía NFR-BE10-2)

Q1 budget (404 si no existe, lo resuelve el endpoint) · Q2 `budget_lines` del escenario
(todas, en un solo scan) · Q3 base de ingresos por mes de causación (ingresos del propio
escenario, espejo `income_budget_by_month` del legacy 02_02 §6) · Q4 AR esperado por mes
(`accounts_receivable.balance` por mes de `due_date` del año, espejo `net_income_by_month`
legacy) · Q5 tasas de internación por set de Líneas (`IN`, como BE-S9 §5.4) · Q6 términos
de internación por set de Líneas (`IN`, orden D-7) · Q7 `iva_periods` del año.

### 4.2 Eventos GENERADOS (recaudo)

| # | Fuente | Fecha del evento | Base | IVA |
|---|---|---|---|---|
| E1 | línea INCOME (behavior fixed — única posible hoy) | `coalesce(payment_date, budget_date)` | `projected_amount` | E1.base × T |

El flag `has_iva` de una INCOME se IGNORA (D-S10-5). Concepto `ventas`.

### 4.3 Eventos DESCONTABLES (pagos)

| # | Fuente | Fecha del evento | Base | IVA |
|---|---|---|---|---|
| E2 | EXPENSE fixed con flag efectivo True (NULL ≡ True) | `budget_date` (causación, D-S10-9 enmendada) | `projected_amount` | base × T |
| E3 | EXPENSE `variable_sales` con flag True | `budget_date` de la línea (aproximación de caja sobre el mes de causación de la base — R-S10-4) | `variable_rate × Q3[mes]` | base × T |
| E4 | EXPENSE `variable_receivables` con flag True | idem E3 | `variable_rate × (Q3[mes] + Q4[mes])` | base × T |
| E5 | PURCHASE — IVA importación | `budget_date` (momento de la compra, D-S10-6) | `Total / (1 + %int)` | base × T |
| E6 | PURCHASE — IVA internación, cuota k | `budget_date` de la compra (causación, D-S10-9 enmendada; las cuotas ya no desplazan la fecha) | `CostoInt × term.payment_pct` (sin términos ⇒ 100 % en la ancla, BR-INT-04 de `02_19`) | base × T |

Reglas compartidas con BE-S9 §4: `%int` irresoluble (sin Línea o sin fila del catálogo) ⇒ 0
⇒ E5 = T×Total y E6 no existe (D-S10-8); guard `pct > 0 Y costo_int > 0` (nota §10.2 de
`02_19`); floats crudos sin redondeo intermedio, round(2) solo en la respuesta; orden
determinístico (fecha, concepto, `id_budget_line` ASC). Flag False ⇒ la línea NO emite
evento (no se emite 0). Bases de E3/E4 idénticas a las del legacy `project_cash_flow`
(B1/B2 de 02_02 §6) para paridad de cifras. El carryover y las cuotas de escenarios N−1
NO generan eventos en v1 (D-S10-12, PQ-S10-2).

### 4.4 Asignación a período

Evento con fecha `d` (año del `budget_year` del escenario o `?year=`) → primer `IvaPeriod`
del año con `date_from ≤ d ≤ date_to` (por `period_no` ASC). Sin calendario del año ⇒
`periods: []` + warning literal `"No IVA calendar for {year}; configure /budget/iva-period"`
y TODO en `unassigned` (nunca error). Eventos fuera del año de liquidación ⇒ contados en
`meta.out_of_year_events` y excluidos. `unassigned` reporta sus sumas por separado y NO
participa de la recurrencia (advierte al usuario en el FE).

### 4.5 Recurrencia de liquidación

```
saldo_favor_0 = 0
para p en periods ordenadas period_no ASC:
    base_p  = generado_p − descontable_p − saldo_favor_{p-1}
    pago_p        = round(max(0, base_p), 2)   # se paga en payment_due_date_p
    saldo_favor_p = round(max(0, −base_p), 2)
```
`pago_p > 0` es el único desembolso del período (A8). `totals` = sumas de columnas + saldo
final. Desglose descontable por concepto en la respuesta:
`fixed_expenses (E2), variable_expenses (E3+E4), import_vat (E5), nationalization_vat (E6)`.

### 4.6 Contrato de respuesta (`IvaSettlementResult`, `app/schemas/budget/ivaSettlement.py`)

```jsonc
{
  "id_budget": 126, "budget_name": "...", "year": 2027,
  "tax_rate_used": 0.19, "basis": "accrual",
  "periods": [{
    "period_no": 1, "date_from": "2027-01-01", "date_to": "2027-02-28",
    "payment_due_date": "2027-05-21", "description": null,
    "generated":  {"ventas": 1900000.0},
    "deductible": {"fixed_expenses": 0.0, "variable_expenses": 0.0,
                   "import_vat": 0.0, "nationalization_vat": 0.0},
    "prior_balance": 0.0, "tax_base": 1900000.0,
    "payment": 1900000.0, "carry_balance": 0.0,
    "events_count": 3
  }],
  "unassigned": {"generated": 0.0, "deductible": 0.0, "events_count": 0},
  "totals": {"generated": 0.0, "deductable": 0.0, "payments": 0.0, "final_balance": 0.0},
  "meta": {"warnings": [], "out_of_year_events": 0,
           "filters": {"id_budget": 126, "year": 2027}}
}
```
---

## 5. Cambios por archivo

### 5.1 `app/models/budget/ivaPeriod.py` (NUEVO) + `budgetLine.py` + `__init__.py`s
§3.2 literal; `has_iva` en `BudgetLine` (§3.1); registro del modelo en `models/budget/__init__.py`
y `models/__init__.py`. Sin nuevas relaciones ORM (catálogo plano, espejo `lineInternmentRate`).

### 5.2 `app/schemas/budget/`
- `ivaPeriod.py` (NUEVO): triple `IvaPeriodBase/Create/IvaPeriod` (`from_attributes=True`);
  `period_year: int = Field(ge=2000, le=2100)`; `period_no: int = Field(ge=1, le=36)`;
  `date_to >= date_from` vía `model_validator` (422); fechas ISO.
- `ivaSettlement.py` (NUEVO): `IvaGeneratedBreakdown`, `IvaDeductibleBreakdown`,
  `IvaSettlementPeriod`, `IvaUnassigned`, `IvaSettlementTotals`, `IvaSettlementMeta`,
  `IvaSettlementResult` — campos §4.6, `Optional` donde §4.4 lo indique.
- `budgetLine.py`: `BudgetLine` gana `has_iva: Optional[bool] = None` (aditivo en toda
  respuesta que serialice la línea).
- `planning.py`: `PlanningLineCreate.has_iva: Optional[bool] = None` y
  `PlanningLineUpdate.has_iva: Optional[bool] = None` (contrato partial: omitido = keep;
  en create, None ⇒ True para expense; en INCOME/PURCHASE se persiste igual el valor
  recibido — la derivación lo ignora, D-S10-5).

### 5.3 `app/crud/budget/ivaPeriod.py` (NUEVO) — espejo de `lineInternmentRate.py`
`get_iva_periods(db, year: Optional[int])` (orden `period_year, period_no`),
`create` (pre-check dup ⇒ `None` ⇒ 400 API-friendly ANTES del IntegrityError), `update`
(full-replacement con el mismo guard de dup en re-parent), `delete` (físico, catálogo sin
historial). T-05: un commit por mutación.

### 5.4 `app/crud/budget/planning.py`
- `create_planning_line`: persiste `has_iva = payload.has_iva if payload.has_iva is not
  None else True`.
- `update_planning_line`: parcial estándar — `has_iva` incluido solo si no es `None`.
- CERO cambios en `build_carryover_payload_lines` / ranks / orígenes (A15/D-S10-12).

### 5.5 `app/services/budgetPlanningIngestion.py`
`build_expense_line_records`: cada dict gana
`"has_iva": record.get("has_iva")` (None si columna ausente → NULL ≡ True en BD, D-S10-3).
Income/purchase builders NO tocan la columna (queda NULL).

### 5.6 `app/utils/templates/budgetTemplates.py` — `process_budget_plan_expense`
- Normaliza `con_iva` con `_clean_column_names` (fila 8: `Con IVA → con_iva`).
- `has_iva = _map_iva_flag(row)`: tolerante, columna OPCIONAL (ausencia ⇒ columna None,
  AC-REG-01 preservado para archivos viejos):

| valor celda (strip+lower) | resultado |
|---|---|
| `si`,`sí`,`yes`,`y`,`x`,`1`,`true`,`verdadero` | `True` |
| `no`,`not`,`n`,`false`,`0`,`falso` | `False` |
| NaN / vacío / cualquier otro | `None` (≡ True por regla D-S10-3) |

- `process_budget_plan_income/purchase`: SIN cambios.

### 5.7 `app/services/budgetIvaEngine.py` (NUEVO) — §4 completo, solo lectura

### 5.8 `app/api/budget/ivaPeriod.py` (NUEVO) — espejo del stack de `lineInternmentRate.py`
`GET /?year=` · `POST /` 201 · `PUT /{id}` · `DELETE /{id}` → `{"deleted_id": id}`;
404 `"IvaPeriod {id} not found"`; 400 `"Period {period_no} already exists for year
{period_year}"`; JWT simple (`get_db` + `get_current_user`, sin role gate — mismo nivel
que los demás catálogos).

### 5.9 `app/api/budget/ivaSettlement.py` (NUEVO)
`GET /budget/iva/settlement/{id_budget}?year=` (year default `budget.budget_year`) →
`IvaSettlementResult`. 404 `"Budget {id_budget} not found"` (CRUD Optional→None); `year`
fuera de [2000,2100] ⇒ 422; escenario sin líneas ⇒ 200 con todo en ceros + `periods` del
calendario. Registro: `app/api/budget/__init__.py` importa y monta
`prefix="/iva-period", tags=["budget"]` y `prefix="/iva", tags=["budget"]`;
`app/main.py` NO cambia (agregador `budget` ya montado).

## 6. Delta de API (resumen)

| Endpoint | Cambio |
|---|---|
| `GET/POST/PUT/DELETE /budget/iva-period/...` | **NUEVO** catálogo §5.8 |
| `GET /budget/iva/settlement/{id_budget}` | **NUEVO** liquidación §5.9 |
| `POST /budget/planning/line`, `PUT /budget/planning/line/{id}` | +`has_iva` opcional (§5.2/§5.4) |
| `POST /budget/planning/upload`, `POST /budget/upload/budget-plan-expense` | leen columna `Con IVA` (opcional) → `has_iva` (§5.5/§5.6) |
| `GET /budget/planning/{id}/detail`, respuestas de línea (cell PUT, line CRUD) | +campo aditivo `has_iva` |
| carryover, clone, cell, set-target, upload-result, P&L, flujos legacy, analytics | **INTACTOS** (D-S10-12) |

## 7. NFR

| ID | Requisito |
|---|---|
| NFR-BE10-1 | El motor de IVA es 100 % lectura: ninguna cuota, evento ni liquidación se materializa; los únicos datos persistidos nuevos son `iva_periods` y el flag `has_iva`. La liquidación se recalcula viva ante cualquier edición (patrón D-S7-2/BR-CO-04) |
| NFR-BE10-2 | Economía: settlement usa ≤8 consultas constantes (Q1–Q7 de §4.1), independientes del número de líneas |
| NFR-BE10-3 | Retrocompat: payloads existentes solo ganan el campo aditivo `has_iva`; datos viejos NULL ≡ True; archivo sin columna ⇒ igual que hoy; sin calendario ⇒ 200 con warning (nunca 500/422) |
| NFR-BE10-4 | Determinismo: orden de eventos (fecha, concepto, id), de períodos (year, period_no), round(2) solo en salida, floats crudos en recurrencia |
| NFR-BE10-5 | Despliegue: UN solo ALTER manual (§10); `iva_periods` la crea `create_all`; cero ALTER TYPE |
| NFR-BE10-6 | Seguridad: JWT en todo; sin gate de roles nuevo; sin datos sensibles nuevos |

## 8. Riesgos y pendientes

| ID | Ítem |
|---|---|
| R-S10-1 | NULL ≡ True sobreestima descuentos IVA de archivos viejos realmente excluidos — ACEPTADO por stakeholder ("manualmente yo haré el cambio") |
| R-S10-2 | Base legal real del IVA de importación = valor en aduana + arancel; la regla del stakeholder es T × CostoProveedor — simplificación ACEPTADA (D-S10-6) |
| R-S10-3 | Pilares 1/2/3 y `project_cash_flow` quedan sin uplift de IVA de egresos (el legacy solo gross-up de recaudo): la ÚNICA vista BE completa es la liquidación; el FE muestra brutos por derivación propia (frontend.03_14) con fórmulas espejo §4 — **ENMIENDA 2026-09-23 (frontend.03_14 D-FE14-7): el bruto SOLO se pinta en la Vista Flujo (y columnas informativas de la Cuadrícula); la Vista Ejecutiva (P&G por causación) se muestra SIEMPRE en netos, sin información de IVA** — riesgo de divergencia mitigado por `TAX_RATE` único y AC espejo |
| R-S10-4 | El IVA de gastos variables se ancla al mes de causación de su base (aproximación de caja) |
| PQ-S10-1 | Ventas 0 %/excluidas (flag en INCOME) |
| PQ-S10-2 | Incluir en la liquidación los pagos de arrastre N−1 (origines cogs/purchase/internment del carryover) |
| PQ-S10-3 | Liquidación REAL contra facturas (`total_with_tax` − `total_without_tax`) y auxiliares, con comparación real-vs-proyectado |
| PQ-S10-4 | ICA, retefuente,arancel y demás tributos |
| PQ-S10-5 | `accounts_payable`/ledger automáticos al vencimiento del pago (`payment_due_date`) |
| PQ-S10-6 | Devolución/compensación de saldos a favor acumulados (regla DIAN: 1 año) |
| PQ-S10-7 | Tasa configurable por categoría/renglón (espejo PQ-S9-5) |
## 9. Criterios de aceptación (BE)

Fixture central `10.000.000` (compra, %int = 0.10 ⇒ CostoProv 9.090.909,09; CostoInt
909.090,91; términos int `+15 @ .6 / +45 @ .4`; términos prov `+30 @ .5 / +60 @ .5`):

- **AC-BE10-1 (ETL/flag):** archivo con `Con IVA = No` ⇒ `has_iva False`; `Si`/`sí`/`X`
  ⇒ True; celda vacía ⇒ None; archivo SIN la columna ⇒ todas None y subida idéntica a hoy
  (AC-REG-01); income/purchase ⇒ None. El flag persiste en `budget_lines` y sale en
  `GET /{id}/detail`.
- **AC-BE10-2 (line manager):** `PUT /line/{id}` `{has_iva:false}` ⇒ reflejado y persistente;
  omitido ⇒ keep; `POST /line` sin campo ⇒ True. El flag de una INCOME se aceita y persiste
  pero NO altera su evento E1 (siempre gravada).
- **AC-BE10-3 (eventos de compra):** fixture 10.000.000 fecha 2027-01-10: E5 = **1.727.272,73**
  en 2027-01-10; E6 = **103.636,36** (2027-01-25) + **69.090,91** (2027-02-24); Σ =
  **1.900.000,00** = T × Total exacto (sin %int: E5 = 1.900.000 en el ancla y cero E6).
- **AC-BE10-4 (recurrencia con arrastre):** calendario 2027 bimestral (ene-feb vence
  2027-05-21…); generado/descontable por período: P1 1.900.000/0 ⇒ pago 1.900.000; P2
  0/2.500.000 ⇒ pago 0, arrastre 2.500.000; P3 3.000.000/1.000.000 ⇒ base −500.000 ⇒ pago
  0, arrastre 500.000; P4 4.000.000/500.000 ⇒ pago 3.000.000, arrastre 0. `prior_balance`
  y `carry_balance` por fila; `totals.final_balance` = arrastre remanente.
- **AC-BE10-5 (catálogo):** POST duplicado (year,no) ⇒ 400 literal; `date_to < date_from`
  ⇒ 422; PUT inexistente ⇒ 404 `"IvaPeriod {id} not found"`; DELETE ⇒ `{"deleted_id": n}`;
  `GET /?year=2027` filtra y ordena.
- **AC-BE10-6 (sin calendario):** settlement 200 con `periods: []`, todo en `unassigned`
  con sumas correctas y el warning literal de §4.4.
- **AC-BE10-7 (gastos e ingresos):** gasto fijo 1.000.000 `has_iva=False` ⇒ cero E2;
  `True/None` ⇒ E2 190.000 en su payment_date; ingreso 10.000.000 ⇒ E1 1.900.000 en fecha
  de recaudo; variable_receivables 8 % con base 500.000.000 gravado ⇒ E4 = 19 % × 40.000.000.
- **AC-BE10-8 (regresión):** `test_budget_*.smoke` existentes verdes; ÚNICO ajuste:
  aserciones de claves exactas de respuestas de línea (campo aditivo `has_iva`) — documentar
  aquí como se hizo en `02_19` §10. Carryover payload byte-idéntico.

**Prueba:** smoke nuevo `crm_backend/test/test_budget_iva_smoke.py` (patrón internment smoke)
cubriendo AC-BE10-1..8, con paridad HTTP-vs-unit del engine (estilo pilares).

## 10. Despliegue (DDL manual — agregar al runbook/note.md del pipeline)

```sql
-- BE-S10-IVA: la ÚNICA mutación DDL manual (patrón BE-S6 include_carryover).
-- create_all NO altera tablas existentes. Ejecutar ANTES de subir código:
ALTER TABLE budget_lines ADD COLUMN IF NOT EXISTS has_iva BOOLEAN;
-- iva_periods: la crea create_all al arrancar (tabla nueva, cero DDL).
-- Sin backfill: NULL ≡ True es regla de la derivación (§3.1), no default de datos.
-- Post-check: SELECT count(*) FROM budget_lines WHERE has_iva IS NOT NULL;  -- 0
```

Compatibilidad FE-BE: el campo `has_iva` es aditivo — clientes FE viejos lo ignoran; el tab
de liquidación exige desplegar BE y FE (`frontend.03_14`) en el mismo release.

### 10.1 Nota de implementación (2026-09-23 — corrida de smokes, estilo nota §10 de `02_19`)

- **AC-BE10-8 CERO CUMPLIDO:** ningún smoke existente necesitó ajuste por el campo aditivo
  `has_iva`. El planning smoke compara líneas vía su tupla canónica `line_key()` (claves
  explícitas, nunca el set completo de la respuesta) y el purchases/internment idem ⇒ la
  predicción "cero ajustes esperados" se verificó empíricamente. `test_budget_iva_smoke.py`
  pasó 62/62 (incluida paridad HTTP-vs-unit y limpieza garantizada 0 restos);
  `test_budget_planning_lines_smoke` 45/45; `test_budget_planning_smoke` 56/56;
  `test_upload_status_smoke` 7/7; `test_budget_smoke` 15/15.
- **HALLAZGOS PRE-EXISTENTES (NO regresión BE-S10 — carryover y derivation intactos):**
  1. `test_budget_planning_smoke` fallaba 15/36 por DERIVA DE ENTORNO, no por código:
     residuos `PLN *` (closed) del 2026-09-15 imposibles de barrer vía API desde que el
     DELETE se hizo draft-only (BE-S14), y `Prueba5` (id 126) ACTIVE en 2027 desde
     2026-09-21 que rompe su precondición "0 activos" (el smoke no cuarentena ajenos,
     patrón que sí tienen pnl/cash-flow). Con residuos borrados por SQL y cuarentena
     temporal de 126 (restaurada después a `active`): 56/56 verdes.
  2. `test_budget_purchases_smoke` 55/56: AC-BE8-5 esperaba payload sin stream de
     internacion, pero el stakeholder ya cargó tasas REALES (Kyly 0.12, Tinta 0.20, …)
     en las Líneas de los CECOS centinela; los montos observados reproducen EXACTAMENTE
     la regla `02_19` §4 (20M/1.12 ⇒ prov 17.86M; int 2.14M×.4 cuota +45 d = 857,142.86).
     Es interacción stakeholder-data×fixture-viejo posterior al commit de BE-S9; ajeno a
     BE-S10. Requiere actualizar `_expected_carryover()` (fuera del scope de esta feature).
  3. `test_budget_internment_smoke` 42/43: su check [2] asume las tablas catálogo NUEVAS
     vacías al arrancar; el stakeholder las pobló en uso real (8 tasas / 16 términos).
     Mismo diagnóstico: drift de dato real sobre supuesto de smoke, no regresión.
  4. Fixture local renombrado (no versionado): el purchases smoke exige
     `test/data/Formato Solicitud Presupuesto Importaciones.xlsx`; la carpeta solo tenía
     `... Importaciones 2026.xlsx` ⇒ se duplicó el contenido al nombre esperado (mismo
     fixture real de 2026 descrito en su docstring).
  5. `test_budget_smoke.py` (el viejo) no reconfigura stdout: en consola cp1252 crasheaba
     el carácter '✓' antes de imprimir resultados; ejecutar con `PYTHONIOENCODING=utf-8`.

## 11. Trazabilidad requisitos → supuestos discutidos

| Supuesto de la sesión | Decisión/BR que lo fija |
|---|---|
| A1/A2 (ingresos gravados, recaudo ×1.19) | D-S10-5, E1 §4.2 |
| A4 revisado (flag por renglón en plantilla) | D-S10-2, §5.6 |
| A5 v2 (compras: import de contado + int por cuota) | D-S10-6/7/8, E5/E6 §4.3 |
| A6 (calendario configurable bimestral tipo 21-may) | D-S10-10, §3.2 |
| A7/A8/A9 (pago al vencimiento, arrastre, sin devolución) | D-S10-11, §4.5 |
| A10/A15 (v1 proyectado, no toca carryover/engines) | D-S10-12, §2 |
| A12/A13 (montos derivados, solo flag materializado) | D-S10-4, NFR-BE10-1 |
| A14 (catálogo satélite con convenciones BE-S9) | §3.2/§5.8 |
| Enmienda stakeholder 2026-09-23: la Vista Ejecutiva (P&G) nunca refleja IVA — el bruto solo vive en el Flujo | frontend.03_14 D-FE14-7/AC-FE14-8 (cero cambio BE: la derivación de liquidación no toca la Ejecutiva) |