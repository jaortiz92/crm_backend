# Spec Backend: Pago a Proveedores por Costo de Ventas (rollback de expansión de gastos + arrastre derivado)

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S7-COGS-PAYFLOW` |
| **Versión** | 1.0 — 2026-09-14 |
| **Status** | **ENMIENDA** a BE-S5 (`backend.02_15`) y BE-S6 (`backend.02_16`). Corrige el objetivo del negocio tras la validación del stakeholder con el escenario de prueba #125. |
| **Contrato** | Autoridad para `frontend.03_10_Spec_frontend_cogs_payment_flow.md` (FE-S7). |
| **Origen** | Validación del stakeholder: "los gastos NO debían diferirse en cuotas — se pagan completos como estaba. El objetivo era diferir el pago al proveedor directo que se genera por el COSTO. Ej: #125, ingreso $10 M de Kyly ⇒ diferir su 60 % (el costo) según los términos indicados." |

---

## 1. Objetivo y ejemplo canónico

Un CECO de ingreso Kyly (Línea 1, `cogs_pct = 60`, términos 34 %/+60 · 33 %/+90 · 33 %/+120) con ingresos fijados $10 M causados 2027-05-30 genera un **pago al proveedor de $6 M** que se difiere: **$2.04 M el 2027-07-29, $1.98 M el 2027-08-28, $1.98 M el 2027-09-27** — visible en la Vista Flujo, **derivado** (no materializado), mientras los gastos del escenario quedan intactos (pago completo).

## 2. ROLLBACK de la expansión de gastos (S5) — reglas superseded

Se RETIRAN de BE-S5: BR-TERM-02..04, BR-TERM-07/09 en lo que respecta a **materialización de cuotas de gasto**, el helper `expand_expense_line`, el flag `expand_payable_terms` (parámetro y su paso en `planning.py` upload) y la expansión del `POST /{id_budget}/line`:

- `app/services/budgetPlanningIngestion.py`: `build_expense_line_records` vuelve a su forma pre-S5 (una fila, `payment_date` del registro tal cual); se elimina el helper de expansión y sus imports muertos. El legacy (`upload.py:416`) y planning quedan IDÉNTICOS entre sí otra vez (más simple: mismo comportamiento para ambos callers).
- `app/crud/budget/planning.py::create_planning_line`: revierte a retornar SOLO la línea creada (sin tuple/siblings); misma transacción y validaciones previas a S5.
- `app/api/budget/planning.py` POST `/line`: `response_model` vuelve a `BudgetLine`. **Se elimina** `PlanningLineCreateResult` de `app/schemas/budget/planning.py` y de los registros de `__init__` (el `expanded_siblings` que aún lee el FE con `?? []` se vuelve benigno — el FE lo retira en FE-S7).
- **PERMANECEN VIVOS (re-semantizados):** tabla `line_payable_terms`, CRUD `linePayableTerm` completo y sus endpoints. Nuevo significado: **"términos con los que pagamos al proveedor el costo de ventas (COGS) de la Línea"** — se aplican SOLO a la derivación de la Vista Flujo (FE-S7, cliente) y al arrastre derivado (§4, server). La escala de `payment_pct` (0–1) y `payment_days` (negativo = antes del ancla) NO cambian.
- Ingresos: `line_payment_rules` (cobro) intacto — BR-ING-05 sigue materializando cuotas de cobro (el stakeholder confirmó que eso está bien).

## 3. Derivación del año propio: en el FE (no server)

Decisión D-S7-2: el bloque "Pago a proveedores (costo)" de VISTA se calcula client-side (FE-S7) porque debe reaccionar en vivo al PUT de celda y a la edición de líneas (AC-FE-6) desde la caché. La única autoridad que replica es la fórmula de costo de `budgetEngine.get_pnl` (pool vigente de `line_cost_rates` por `id_line_cost_rate DESC`, `cogs_pct` escala **0–100**, vigencia por month-end ∈ [date_from, date_to]) — el FE la espeja ya en Ejecutiva; la derivación de pagos toma el MISMO pct resuelto por mes.

## 4. Arrastre BE-S6: extensión derivada (BR-CO-09..)

`GET /budget/planning/{id_budget}/carryover` mantiene las líneas materiales de la fuente (BR-CO-03, fijas con fecha efectiva ∈ N — siguen vigentes para gastos con fecha de pago manual del año anterior) y **ADEMÁS** deriva cuotas de costo de las líneas de INGRESO de la fuente:

- **BR-CO-09:** para cada línea de ingreso `fixed` de la fuente (año N−1): `pct = cogs` vigente de su Línea al month-end de `budget_date` (misma regla §3; CECO sin `id_line` o sin tasa ⇒ sin fila); `costo = monto × pct/100`; por cada término de la Línea: `payment_date = budget_date + payment_days`, `amount = costo × payment_pct`; **sin términos ⇒ una fila 100 % con `payment_date = budget_date`** (D-S7-4). Se incluyen SOLO filas con año(payment_date) == N.
- **BR-CO-10:** cada fila del payload gana `origin`: `"line"` (material, comportamiento previo) o `"cogs"` (derivada de costo; `id_budget_line` = `null`, `budget_date` = ancla de la línea de ingreso origen, `description` = `"Costo de venta (arrastre)"`, `line_type = "expense"`). Orden del array: material-asc y cogs-asc por fecha efectiva (estable; campo secundario `id null-safe`).
- **BR-CO-11:** la derivación se computa por request (dinámica, sin cache server — coherente con BR-CO-04) y cuesta ≤2 consultas extra (tasa pool vigente + términos por Líneas distintas de la fuente).
- PUT flag sin cambios.

## 5. AC (smoke BE)

- **AC-S7-BE-1:** POST `/line` de gasto fijo (CECO con términos) ⇒ UNA fila, `payment_date` del body respetado, respuesta = `BudgetLine` puro (sin `expanded_siblings`).
- **AC-S7-BE-2:** upload planning de egresos (con términos en la Línea) ⇒ salida idéntica a pre-S5 (fecha de pago del archivo intacta); legacy sin cambios.
- **AC-S7-BE-3:** `line_payable_terms` + CRUD siguen operativos (smoke S5-BE-8 repe).
- **AC-S7-BE-4:** escenario N con flag ON y fuente N−1 con ingreso $10 M (Línea con cogs 60 y términos 34/60,33/90,33/120 causados en dic de N−1) ⇒ carryover incluye 3 filas `origin:"cogs"` ene/mar de N con $2.04M/$1.98M/$1.98M; además las fijas materiales como antes (`origin:"line"`).
- **AC-S7-BE-5:** ingreso fuente con cogs pero SIN términos ⇒ una fila `cogs` 100 % en la fecha del ingreso si cae en N (si no, excluida).
- **AC-S7-BE-6:** CECO fuente sin tasa cogs vigente al month-end ⇒ cero filas derivadas (degradación silenciosa).
- **AC-S7-BE-7:** openapi: `PlanningLineCreateResult` ausente; `POST /line` 201 = `BudgetLine`; `PlanningCarryoverLine` con `origin` enum `"line"|"cogs"` y `id_budget_line` nullable.
- **AC-S7-BE-8:** GET carryover con flag OFF sigue devolviendo `enabled:false, lines:[]` (la derivación §4 solo corre con flag ON).

## 6. Decision Log

| ID | Decisión |
|---|---|
| D-S7-1 | El catálogo de términos se re-semantiza (costo→proveedor), no se crea tabla nueva |
| D-S7-2 | Derivación del año propio SOLO en FE (reactividad AC-FE-6); costo NUNCA se materializa en `budget_lines` |
| D-S7-3 | Arrastre de cuotas de costo derivado server-side (la fuente N−1 no puede reaccionar en el cliente) |
| D-S7-4 | Sin términos ⇒ pago del costo al 100 % el día de la ancla (`budget_date` del ingreso) |
| D-S7-5 | Ancla = `budget_date` de la línea de ingreso (la cuota de cobro NO re-ancla el costo) |
| D-S7-6 | Rollback total de la expansión de gastos (no banderado "apagado") — menos deuda viva |

## 7. Checklist

1. Revert ingestion/crud/api POST + borrar schema/helper (§2). 2. `origin` en `PlanningCarryoverLine` + derivación §4 en `get_carryover_lines`/endpoint. 3. Smoke AC-S7-BE-1..8 (throwaway DB). 4. Abrir/validar openapi. 5. ⇒ FE-S7.