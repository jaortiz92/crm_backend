# SPEC backend.02_28 — Gasto variable por salidas de dinero (`variable_outflows`)

> Estado: APROBADA (implementar)
> Fecha: 2026-11-11
> Módulos afectados: `app/models/budget/budgetLine.py`, `app/schemas/budget/budgetLine.py`, `app/schemas/budget/planning.py`, `app/utils/templates/budgetTemplates.py`, `app/services/budgetIvaEngine.py`, `app/services/budgetEngine.py` (`project_cash_flow`), migración manual del enum en PostgreSQL
> Specs relacionadas: backend.02_02 §6 (bases B1/B2, Enmienda E-02), backend.02_24 (base por CECO, Enmiendas A-01/A-02 — esta spec NO reatribuye por CECO), backend.02_20 §4 (E1..E6), backend.02_17 (financiación), backend.02_23 (planeación tributaria), backend.02_10 (cash flow). Spec madre: `spec/04_Spec_Gasto_variable_por_salidas.md`. Espejo frontend: `crm_frontend/spec/frontend.03_25_Spec_frontend_variable_expense_outflows.md`.

---

## 1. Contexto y problema

Hoy existen dos comportamientos de gasto variable (`behavior_type`) cuya base es un
INGRESO del presupuesto:

* **B1 (`variable_sales`, "Variable por Facturación")**: `rate × I_c(m)` — facturación
  presupuestada del CECO resuelto (Enmienda A-01), mes de `budget_date`.
* **B2 (`variable_receivables`, "Variable por Recaudo")**: `rate × R_c(m)` — recaudo del
  CECO resuelto por mes de cobro (Enmienda A-02).

El usuario necesita un **tercer tipo** cuya base son las **SALIDAS de dinero del flujo del
mes**: si en enero las salidas suman 1.000.000 y la tasa es 0,4 %, el gasto agrega 4.000 y
la salida total queda en 1.004.000.

## 2. Historia de usuario

> En la plantilla de gastos existen gastos variables de acuerdo al recaudo y al ingreso.
> Quiero una tercera opción: un gasto relacionado con las salidas de dinero. En enero las
> salidas del flujo sumaron 1.000.000; el gasto variable de 0,4 % debería sumar 4.000 a la
> salida, es decir, la salida total sería 1.004.000, y el gasto variable sumaría 4.000
> según el CECO en el que se ingresó.

### Ejemplo de referencia (presupuesto 576, decisión D1 del usuario)

| Concepto | Ene | Feb | Mar |
|---|---:|---:|---:|
| Salidas Inicial (base) | 72.375.235,31 | 81.152.462,31 | 100.154.457,30 |
| Gasto 0,4 % | 289.500,94 | 324.609,85 | 400.617,83 |
| Salidas (total) | 72.664.736,25 | 81.477.072,16 | 100.555.075,10 |

La identidad `Salidas(m) = Base(m) + tasa × Base(m)` debe cumplirse EXACTA (a 2 decimales
en presentación) para los 12 meses.

## 3. Alcance

### 3.1 In-scope
1. Nuevo valor de enum `BehaviorTypeEnum.VARIABLE_OUTFLOWS = "variable_outflows"`
   (modelo + espejo Pydantic + descripciones de campo).
2. Parseo en la plantilla de gastos: `"Variable por Salidas": "variable_outflows"` en
   `behavior_map` (columna `comportamiento`).
3. Rama de cálculo en `BudgetEngine.project_cash_flow` (tercera rama tras B1/B2), con
   espejo de base mensual `Base(m)` (§5.5).
4. Exclusión EXPLÍCITA en `BudgetIvaEngine` (§5.4): el tipo NO es deducible, no emite
   eventos de liquidación IVA.
5. Migración manual del enum PostgreSQL para bases existentes (§5.7).

### 3.2 Out-of-scope
1. **NO cambiar** `fixed`, `variable_sales` ni `variable_receivables` (bases A-01/A-02 intactas).
2. **NO** resolución de CECO por cubeta (`cecoBucketUtils`) para este tipo: la base es
   GLOBAL del presupuesto; el aporte se contabiliza en el CECO propio de la línea.
3. **NO** cálculo iterativo / punto fijo: la base excluye el resultado de TODAS las líneas
   `variable_outflows` (determinista, una sola pasada).
4. **NO** tocar `project_cash_flow` de más ni `get_cash_flow` (Pilar 2, curva de liquidez
   ledger-relativa, L1124+) — queda intacto.
5. **NO** tocar P&L de devengo (AC-UP-1 ya fuerza `projected_amount = 0` para variables).
6. Plantilla de ingresos (hard-stamp `fixed`, sin cambio) y guardas CRUD genéricas
   (`!= FIXED` / `== FIXED` ya aplican; solo verificar con tests).

## 4. Definiciones

| Término | Definición |
|---|---|
| **Tasa** (`rate_v`) | `budget_lines.variable_rate` (decimal, ej. 0,004 = 0,4 %). Obligatoria. |
| **Mes de causación** | `extract(month, budget_date)` de la línea (igual convención que B1). |
| **CECO propio** | `budget_lines.id_cost_center` de la propia línea (SIN resolver). |
| **Base(m)** | Suma de TODAS las salidas del presupuesto en el mes `m`, EXCLUYENDO el aporte de TODAS las líneas `variable_outflows`. Composición §5.5. |
| **Aporte de la línea v** | `aporte_v = rate_v × Base(mes(budget_date de v))` si el año de `budget_date` == año del presupuesto; si no, 0. |

## 5. Especificación técnica

### 5.1 Modelo — `app/models/budget/budgetLine.py` (L33-36)
```python
class BehaviorTypeEnum(str, enum.Enum):
    FIXED = "fixed"
    VARIABLE_SALES = "variable_sales"
    VARIABLE_RECEIVABLES = "variable_receivables"
    VARIABLE_OUTFLOWS = "variable_outflows"   # NUEVO (backend.02_28)
```
Columna `behavior_type` (L64): sin cambio. **No usar Alembic** (el proyecto usa
`create_all`); la migración es manual (§5.7).

### 5.2 Schemas
* `app/schemas/budget/budgetLine.py` L25-28: espejo `VARIABLE_OUTFLOWS = "variable_outflows"`.
  L50: descripción del campo → `"...variable_receivables, variable_outflows"`.
  El validador de `variable_rate` (L94-100) ya es genérico (`!= FIXED` ⇒ tasa requerida): SIN cambio.
* `app/schemas/budget/planning.py` L149: misma actualización de la descripción.
  `PlanningLineUpdate` (L196-199) sigue excluyendo `behavior_type` (BR-LINE-06): sin cambio.

### 5.3 Plantilla de gastos — `app/utils/templates/budgetTemplates.py` (L1512-1522)
```python
behavior_map = {
    "Fijo": "fixed",
    "Variable por Facturación": "variable_sales",
    "Variable por Recaudo": "variable_receivables",
    "Variable por Salidas": "variable_outflows",   # NUEVO
}
```
El split monto/tasa (L1528-1533) y la ingesta (`budgetPlanningIngestion.py` L232-237, con
`has_iva` L250-257) ya son genéricos (`!= "fixed"` ⇒ `projected_amount = 0`, monto→`variable_rate`):
SIN cambio lógico. Verificar con test que una fila "Variable por Salidas" ingesta con
`behavior_type="variable_outflows"`, `variable_rate` correcto y `projected_amount=0`.

### 5.4 Motor IVA — `app/services/budgetIvaEngine.py`  ⚠️ CAMBIO CRÍTICO
Entre la rama `variable_receivables` (L407-443) y el `else` fijo (L444-449) agregar rama
explícita de EXCLUSIÓN:

```python
elif behavior == "variable_outflows":
    # backend.02_28 BR-VS-04: NO deducible; la línea no emite eventos de
    # liquidación IVA (E1..E6). La base de `variable_outflows` incluye los
    # impuestos, por lo que una deducción crearía circularidad.
    continue
```

**Por qué es obligatorio:** hoy cualquier `behavior` desconocido cae al `else` (L444-449)
que emite E2 (gasto fijo deducible) — eso deduciría el gasto por salidas, cambiaría el IVA
a pagar, y rompería la identidad del ejemplo. Actualizar el docstring E1..E6 (L21-35)
documentando que `variable_outflows` no emite eventos. `_enum_value` (L109-116) ya
normaliza miembro/varchar: sin cambio.

### 5.5 Motor de flujo — `app/services/budgetEngine.py` (`project_cash_flow`, L89-401)

**(a) Espejo de base mensual.** Tras las ramas B1 (L308-341) y B2 (L343-383), componer:

```
Base(m) = AP(m)            # ya acumulado en outflows_by_month por due_date (L155-172)
        + Fixed(m)         # ya acumulado, con filtro ap_keys (L296-299)
        + SalesVar(m)      # Σ rate × I_c(m) — ya computado en la rama B1
        + ReceivVar(m)     # Σ rate × R_c(m) — ya computado en la rama B2
        + Financing(m)     # NUEVO: cuotas de CAPITAL de financiación
        + Impuestos(m)     # NUEVO: pagos de impuestos del presupuesto
```

Implementación recomendada: acumulador nuevo `base_outflows_by_month: Dict[int, float]`
que se llena EN PARALELO con `outflows_by_month` en los 4 acumuladores existentes (AP,
fixed, B1, B2), más dos consultas nuevas:

* **Financing(m)** — patrón idéntico a `get_cash_flow` L1339-1367:
  ```python
  # cuotas de CAPITAL (solo principal) de créditos activos, revisión vigente,
  # estado "projected", por mes de principal_due_date en el año del presupuesto
  db.query(FinancingCreditInstallmentModel)  # join FinancingCredit status=="active",
      # schedule_revision == FinancingCredit.schedule_revision,
      # projection_status == "projected"
      # -> (extract(month, principal_due_date), Σ principal_amount)
      # filter: extract(year, principal_due_date) == budget_year
  ```
  SOLO capital (principal): los intereses/seguros ya materializan líneas de gasto
  (`source_engine = "financing_credit"`, `_materialize_expenses`) y entran en Fixed(m).

* **Impuestos(m)** — patrón idéntico a `get_cash_flow` L1303-1324:
  ```python
  # BudgetTaxResultModel del presupuesto (id_budget == resuelto por budget_scope):
  #   (a) balance_payable en payment_date dentro del año  -> month(payment_date)
  #   (b) cash_advance en tax_cash_advance_date() (o payment_date) -> idem
  # usar aggregate_tax_cash_flow + tax_cash_advance / tax_cash_advance_date de
  # app/services/budgetTaxEngine.py (ya importados en L61-67)
  ```

**(b) Rama por línea** (réplica de B1/B2, SIN espejo por CECO):
```python
variable_outflows_query = (
    self.db.query(
        extract("month", BudgetLineModel.budget_date).label("accrual_month"),
        BudgetLineModel.variable_rate,
        BudgetLineModel.id_cost_center,          # solo para traza/agrupación frontal
    )
    .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
    .filter(
        budget_scope,
        BudgetLineModel.line_type == "expense",
        BudgetLineModel.behavior_type == "variable_outflows",
        extract("year", BudgetLineModel.budget_date) == budget_year,
    )
)
for row in variable_outflows_query.all():
    rate = float(row.variable_rate) if row.variable_rate else 0.0
    month = int(row.accrual_month)
    outflows_by_month[month] += rate * base_outflows_by_month[month]
```

**(c) Convenciones del motor:** floats crudos (sin round intermedio), `round(2)` solo en
la respuesta (NFR-BE10-4); cero-fill `{m: 0.0 for m in range(1, 13)}`; consultas de número
de round trips constante (sin N+1). Docstring `expected_outflows` (L100-110): documentar
que incluye la tercera rama y que `Base(m)` excluye los aportes `variable_outflows`.

**(d) Invariante BR-VS-06:** `outflows_by_month[m] - base_outflows_by_month[m] ==
Σ aportes variable_outflows(m)`. Agregar aserción/test que la verifique.

### 5.6 CRUD — `app/crud/budget/planning.py` (solo VERIFICAR, sin cambio)
* L505-510 (guarda compra `!= FIXED` ⇒ 400 `PURCHASE_SHAPE_REASON`), L523-525 y L607-609
  (`projected_amount = 0` / rechazo en variables): genéricas, aplican al nuevo valor.
* L839 / L969 (carryover `== BehaviorTypeEnum.FIXED`): las variables ya quedan excluidas.
* Agregar/registrar tests que cubran el nuevo valor en cada guarda (§8).

### 5.7 Migración de datos (bases existentes) — EJECUTAR ANTES DEL DESPLIEGUE
`Base.metadata.create_all` NUNCA altera un enum ya creado (note.md L60). En la base
(dev: postgres :5433 de `docker-compose-dev.yaml`; prod: su DDL de despliegue):

```sql
ALTER TYPE behaviortypeenum ADD VALUE 'variable_outflows' AFTER 'variable_receivables';
```

En PostgreSQL 16 puede ejecutarse dentro de una transacción, pero el nuevo valor NO es
usable hasta hacer COMMIT. Verificar con `SELECT unnest(enum_range(NULL::behaviortypeenum));`.

## 6. Reglas de negocio (resumen normativo)

| ID | Regla |
|---|---|
| BR-VS-01 | `Base(m)` = AP + Fixed (filtro `ap_keys`) + SalesVar + ReceivVar + Financing(capital) + Impuestos; EXCLUYE el aporte de todas las líneas `variable_outflows`. |
| BR-VS-02 | `aporte_v = rate_v × Base(mes(budget_date de v))`; año de `budget_date` == año del presupuesto; tasa nula ⇒ 0 (validación la exige). |
| BR-VS-03 | Cada línea aporta independiente (N líneas ⇒ N aportes acumulados); el CECO NO altera la base. |
| BR-VS-04 | NO deducible en IVA: sin eventos E1..E6; rama de exclusión explícita (§5.4). |
| BR-VS-05 | Validaciones idénticas a los otros variables: tasa obligatoria, `projected_amount = 0` (AC-UP-1), `behavior_type` inmutable (BR-LINE-06), no elegible como compra, sin carryover. |
| BR-VS-06 | Identidad: `Salidas(m) = Base(m) + Σ aportes(m)`, exacta a 2 decimales en presentación. |

## 7. Criterios de aceptación (backend)

| ID | Criterio |
|---|---|
| AC-BE-VS-1 | El enum acepta `variable_outflows`; crear línea sin `variable_rate` ⇒ 400 (mismo código que los otros variables). |
| AC-BE-VS-2 | La plantilla de gastos ingesta "Variable por Salidas" con `variable_rate` y `projected_amount=0`. |
| AC-BE-VS-3 | `project_cash_flow`: con Base(Ene)=72.375.235,31 y tasa 0,004 ⇒ `expected_outflows[Ene] = 72.375.235,31 + 289.500,94 = 72.664.736,25` (±0,01). |
| AC-BE-VS-4 | Dos líneas `variable_outflows` (CECO A y B, 0,004 c/u) con Base=1.000.000 ⇒ `outflows` total 1.008.000 (4.000 por cada una). |
| AC-BE-VS-5 | Línea con `budget_date` en el año siguiente ⇒ aporte 0 en el año actual (filtro de año). |
| AC-BE-VS-6 | Agregar líneas `variable_outflows` NO altera la salida del settlement IVA (`BudgetIvaEngine.settlement/events`) respecto a ejecutar sin ellas. |
| AC-BE-VS-7 | Guardas: no elegible como compra (400 `PURCHASE_SHAPE_REASON`), sin carryover, `behavior_type` inmutable tras crear. |
| AC-BE-VS-8 | `Base(m)` de backend == composición de filas de salida de la Vista Flujo frontend, mes a mes (AC-VS-10 de la spec madre). |

## 8. Plan de pruebas (backend)

Extender en `crm_backend/test/`:
1. `test_budget_planning_smoke.py` (L425-433 y afines): fixture con línea
   `variable_outflows` — creación, validación de tasa, `projected_amount=0`, edición
   bloqueada de `behavior_type`.
2. `test_budget_purchases_smoke.py` (L655): la línea NO es elegible como compra.
3. `test_budget_internment_smoke.py` (L783): carryover la excluye.
4. `test_budget_iva_smoke.py` (L63-68, L842): rama de exclusión — el settlement IVA no
   emite eventos para el nuevo comportamiento (y NO cae en la rama fija E2).
5. Nuevo test de motor: presupuesto con AP + fijos + variable_sales + variable_receivables
   + financiación + impuestos; `project_cash_flow` verifica la fórmula completa de §5.5 y
   el invariante BR-VS-06; replica los números del §2.
6. Smoke de ingesta: fila "Variable por Salidas" de la plantilla.