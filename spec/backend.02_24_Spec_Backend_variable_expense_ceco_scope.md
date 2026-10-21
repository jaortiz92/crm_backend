# SPEC backend.02_24 — Gastos variables con base por CECO (variable expense CECO scope)

> Estado: PROPUESTA
> Fecha: 2026-10-20
> Módulos afectados: `budgetEngine.py` (Pilar 4, cash flow), `budgetIvaEngine.py` (E3/E4)
> Specs relacionadas: backend.02_02 §6 (bases B1/B2, Enmienda E-02), backend.02_10
> (cash flow engine), backend.02_20 §4 (E3/E4 espejo IVA), frontend.03_21
> (pivotes frontend espejo de esta regla).

---

## 1. Contexto y problema (bug reportado)

Hoy la fórmula de gastos variables (líneas `expense` con
`behavior_type ∈ {variable_sales, variable_receivables}`) calcula el monto
como `tasa × base mensual GLOBAL del presupuesto`:

* **B1 (`variable_sales`)**: `income_budget_by_month[m]` = Σ facturación
  presupuestada de **TODOS** los CECOs del mes `m` (01_02 §6 base B1,
  permanencia como estrategia interpretativa).
* **B2 (`variable_receivables`)**: `net_income_by_month[m]` = Σ de (AR vencido
  del mes + ingreso presupuestado) de **TODOS** los CECOs del mes `m`.

**Evidencia del bug** (`budgetEngine.py` líneas 215–266; idéntico en
`budgetIvaEngine.py` E3/E4 y en `executivePivot.js` / `cashFlowPivot.js`):

```python
outflows_by_month[month] += income_budget_by_month[month] * rate   # B1
outflows_by_month[month] += net_income_by_month[month] * rate      # B2
```

**Síntoma observable**: en el planning (`/budget/planning/573`), el bloque
"Gastos variables (calculados)" muestra **el mismo monto** para todos los
CECOs en un mismo mes (p. ej. comisiones de Enero). Ejemplo: si la comisión
general es 8% y todas las zonas tienen tasa 8%, cada CECO recibe
`0.08 × facturación total de la empresa` en vez de
`0.08 × facturación de su propia zona+línea`.

**Regla de negocio real**: el 8% de comisión (o cualquier otro costo variable:
despachos, etc.) se causa sobre la facturación (o recaudo) **de la zona y
línea que atiende ese CECO**, y ese monto se imputa al CECO correspondiente.
El CECO ya mapea zona+línea (`cost_centers.id_zone` + `cost_centers.id_line`).

## 2. Historia de usuario

> Como usuario del planning, agregué una línea de gasto variable por cada
> concepto aplicable (comisiones, despachos, etc.) para cada CECO (zona+línea),
> con su tasa respectiva y su modo de base (facturado / recaudo). Espero que
> cada CECO muestre el monto variable calculado sobre SU propia facturación o
> recaudo, no sobre el total global.

## 3. Alcance

### 3.1 In-scope
1. Cambiar la base de cálculo de B1 y B2 de "mes global" a "mes por CECO"
   subjacente a cada línea variable:
   * B1c (variable_sales): `facturación presupuestada del mes m DEL CECO de la línea`.
   * B2c (variable_receivables): `(AR vencido del mes m + ingreso presupuestado
     del mes m) DEL CECO de la línea`.
2. Ejercicio fiscal E3/E4 espejo (`budgetIvaEngine.py`): misma base por CECO,
   para que el IVA del gasto variable sea consistente con el monto calculado.
3. Gozoforos derivados (documentados para traza; la implementación frontend es
   spec frontend.03_21): cualquier endpoint que recipe B1/B2 por fila.

### 3.2 Out-of-scope
1. Cambios de modelo / migración de datos (no hay montos materializados; la
   base y el monto son calculados en tiempo de presentación).
2. Cambios al catálogo de tasas (`line_cost_rates`, `commission_rates`): siguen
   siendo catálogos de Pilar 1 / Pilar 3, NO participan en esta fórmula.
3. Tasas nuevas o UI de carga de tasas (lo que existe ya es correcto).
4. El P&L de devengo (Pilar 1): BR-16 de 02_02 declara que `variable_rate` es
   solo mecánica de cash flow; Pilar 1 NO se toca (los gastos variables no
   materializan `projected_amount` — AC-UP-1 — y esa es su conducta actual).
5. La fórmula de la Vista Ejecutiva del backend no cambia; lo que cambia es la
   FUENTE de la base (por CECO en vez de global).

## 4. Definiciones

| Término | Definición |
|---|---|
| **CECO de la línea** | `budget_lines.id_cost_center` de la línea de gasto variable. |
| **Facturado del CECO, mes m** (`I_c(m)`) | Σ `projected_amount` de líneas `income` con `budget_date` en año+m y `id_cost_center = c`. |
| **Recaudo esperado del CECO, mes m** (`R_c(m)`) | `I_c(m) + AR_c(m)`, donde `AR_c(m)` = Σ `balance` de `account_receivables` con `due_date` en año+m y `id_cost_center = c`. |
| **Tasa de la línea** (`rate_v`) | `budget_lines.variable_rate` (decimal, 0–1). |
| **Mes de causación** | `extract(month, budget_date)` de la línea `v` (sin cambio). |

Notas:
* `I_c(m)` SIEMPRE neto (sin IVA) — D-FE14-7 se mantiene; la base jamás
  incluye IVA.
* El mapeo zona+línea→CECO vive en `cost_centers`; NO se usa `id_line` en la
  búsqueda: la línea variable ya trae su `id_cost_center` (requisito de datos,
  ver §6.2).

## 5. Fórmula nueva

### 5.1 Antes (Bug)
```
B1: outflow(m) = Σ_v rate_v × I_global(m)      ← base de todo el presupuesto
B2: outflow(m) = Σ_v rate_v × R_global(m)
E3: iva_v(m)  = rate_v × I_global(m) × T
E4: iva_v(m)  = rate_v × R_global(m) × T
```

### 5.2 Después (esta spec)
```
B1c: outflow(m) += Σ_v∈variable_sales,  m=v.budget_date.month   rate_v × I_c(m)
B2c: outflow(m) += Σ_v∈variable_receivables, m=v.budget_date.m  rate_v × R_c(m)
E3c: iva_v   = rate_v × I_c(m) × T
E4c: iva_v   = rate_v × R_c(m) × T
```
Con `c = id_cost_center de la línea v`.

### 5.3 Reglas de cálculo (BR-VE-*)
* **BR-VE-01** — La causación del mes NO cambia: el monto cae en el mes de
  `budget_date` de la línea variable (permanece lo de E-02: nunca en
  `payment_date`, nunca en su propio `projected_amount`).
* **BR-VE-02** — `I_c(m) = 0` (o CECO sin líneas de ingreso el mes `m`) ⇒
  aporte de esa línea para ese mes = `0`. **No** produce exclusión anual ni
  error (a diferencia del pivote de costo de ventas D-2/D-3, aquí una ausencia
  de ingreso simplemente genera 0, coherente con "no vendió ⇒ no causa
  comisión").
* **BR-VE-03** — Dos o más líneas variables del mismo CECO y mismo mes se
  iteran por fila (cada una aplica su tasa sobre la MISMA base del CECO);
  ninguna tasa se agrupa ni se deduplica (se mantiene el patrón por-row actual).
* **BR-VE-04** — Suma por mes para el CECO total: el total de gastos variables
  del mes `m` a nivel de presupuesto = Σ_c (Σ_v tasa×base_c(m)), es decir,
  la suma de los CECOs. El total por CECO puede diferir del monto global
  calculado hoy; el consolidado solo coincide si cada CECO pesa exactamente
  igual que su tasa (coincidencia que hoy es un bug, no una meta).
* **BR-VE-05** — Redondeo a 2 decimales en los salidas (igual que hoy).
* **BR-VE-06** — CECO NULL en `account_receivables` (AR sin CECO): si la
  tabla AR tiene filas con `id_cost_center IS NULL`, su saldo NO se imputa a
  ningún `R_c(m)` (queda fuera de la base B2c). Debería ser imposible si
  AR siempre tiene CECO; se documenta por si aparecieran huérfanes. NINGÚN
  dato de hoy depende de esto; si existiera AR sin CECO, su parte no entra
  (definición conservadora y auditable).
* **BR-VE-07** — IVA espejo (E3c/E4c) usa LA MISMA base por CECO que B1c/B2c,
  con el mismo `budget_date` de causación; el coeficiente deducible sigue
  "deductible" y las reglas S10 (has_iva, flag, derived) no cambian.

## 6. Puntos de cambio exactos (backend)

### 6.1 `app/services/budgetEngine.py` — `project_cash_flow`
1. **Ingresos**: la query de `income_rows` (líneas ~164–180) agrega SOLO por
   `budget_month`. Agregar `id_cost_center` al SELECT y al `group_by`, y
   poblar un dict `income_ceco_by_month: Dict[int, Dict[int, float]]`
   `[CECO][mes] = I_c(m)`. El `net_income_by_month` / `income_budget_by_month`
   globales se conservan para las otras fórmulas de ese motor.
2. **AR**: la query de `ar_rows` (líneas ~121–133) agrega por `due_month`.
   Agregar `id_cost_center` y poblar `ar_ceco_by_month[c][m]`.
   `net_income_by_month` global se conserva.
3. **B1** (líneas ~222–241): el SELECT agrega `BudgetLineModel.id_cost_center`;
   el aporte pasa a ser
   `income_ceco_by_month[c][month] * rate`.
4. **B2** (líneas ~243–266): mismo patrón; base =
   `income_ceco_by_month[c][month] + ar_ceco_by_month[c][month]`.
5. CECO `"null"` — si `id_cost_center` fuera NULL en alguna línea variable
   (hoy es NOT FK-nullable=False en el modelo; no debería ocurrir), la línea
   aporte 0 y se registra en el log de degradación (mismo estilo que otros
   motores).

### 6.2 `app/services/budgetIvaEngine.py` — E3/E4 (líneas ~300–323)
1. Poblar el espejo `income_by_month` como dict por CECO (igual folio que el
   cash flow: `income_ceco_by_month[c][m]`); idem `ar_by_month`.
2. E3: `base = rate * income_ceco_by_month[c][line.budget_date.month]`.
3. E4: `base = rate * (income_ceco_by_month[c][m] + ar_ceco_by_month[c][m])`.
4. El atributo `c` sale de `line.id_cost_center`.

### 6.3 Otros motores
* Si otro motor usa B1/B2 (verificar `grep -n "income_budget_by_month" |
  grep -v spec`), aplicar el mismo patrón por CECO. Al 2026-10-20 solo existen
  `budgetEngine.py` y `budgetIvaEngine.py`.

## 7. No funcionales

* **NFR-1** — Sin cambios de esquema ni de API (los endpoints existing
  responden mismo shape; solo cambian los NUMEROS calculados).
* **NFR-2** — Sin backfill ni migración. Los escenarios existentes cambian el
  resultado presentado automáticamente al refrescar (es el propósito).
* **NFR-3** — Rendimiento: agregar `id_cost_center` al group_by no cambia la
  complejidad (el target es por-CZC; la matriz 12×CECOs es pequeña). Sin N+1.
* **NFR-4** — Autenticación/sesión: sin cambios.
* **NFR-5** — Compatibilidad de tests: los smoke tests existentes que naturalizan
  la base global (p. ej. `test_budget_planning_smoke.py`, los de IVA) deberán
  recalibrar aserciones de montos variables; nada de shape/estructura cambia.

## 8. Criterios de aceptación (backend)

| ID | Criterio |
|---|---|
| AC-BE24-1 | Dos CECOs `A` (ingreso Enero 100, tasa comisión 8%) y `B` (ingreso Enero 500, misma tasa 8%) en un escenario: comisión Enero `A` = 8, `B` = 40. ANTES ambos salían `0.08 × 600 = 48`. |
| AC-BE24-2 | La misma prueba en modo `variable_receivables` con `AR` de CECO: base = ingreso del CECO + AR del CECO (no global). |
| AC-BE24-3 | CECO sin ingreso en el mes ⇒ aporte 0, sin error ni exclusión. |
| AC-BE24-4 | Dos líneas variables del mismo CECO/mes con tasas 8% y 4% ⇒ aportes independientes (12% sobre la base del CECO). |
| AC-BE24-5 | El total mensual de "Gastos variables" en la respuesta del backend = suma de sus CECOs. |
| AC-BE24-6 | E3c/E4c del IVA espejo usan las mismas bases por CECO (cifra de IVA consistente con el monto de gasto variable). |
| AC-BE24-7 | Sin regresiones en los smoke tests recalibrados: shape, auth y demás invariantes intactos. |

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Los CECOs no tienen línea de ingreso con su CECO (ingresos históricos cargados con otro CECO o NULL) ⇒ bases por CECO = 0 en muchos meses. | Diagnostics: en el `upload/dashboard` / metadata de planning, el conteo de líneas de ingreso por CECO debe cubrir todos los CECOs con líneas variables. El usuario confirma con el caso real 573. |
| AR con CECO distinto del de facturación del mismo negocio (mismatch zona). | Se resuelve al corregir el catálogo UPSTREAM (los códigos de CECO en la carga), no en esta fórmula. Documentado. |
| Doble cuenta en el efectivo: ahora cada CECO aporta su gasto, sumado a level presupuesto. | Los totales por mes del backend = Σ_c(v). No hay doble cuenta: la suma por CECO ES el total. |

---

## 10. Enmienda A-01 — resolución por (zona, línea)

> Fecha de la enmienda: **2026-10-20**
> Origen: validación real contra el escenario 573 (BD dev).

### 10.1 Hallazgo

En el plan de cuentas real, los CECOs de **ingreso** ("Facturación …", código
`000xxx`, ids 151–181) están **desacoplados por diseño** de los CECOs de
**gasto variable** ("Comisiones …" `210xxx` / "Despacho …" `320xxx`, ids
8–120). Es decir: los CECOs sobre los que el usuario carga las líneas
variables de comisiones/despachos **no tienen** (ni tendrán) líneas de
ingreso propia ⇒ la base por CECO `I_c(m)` del §5/§6 produce **0 para todos**,
exactamente el dato del escenario 573.

### 10.2 Regla de resolución (nueva)

La base se resuelve por **(id_zone, id_line)** del CECO de la línea variable
contra los CECOs que SÍ tienen ingreso:

1. **Propio CECO primero** (compatibilidad): si el CECO de la línea variable
   ya tiene base de ingreso (`I_c(m)` poblada), se usa el CECO propio tal
   cual (líneas creadas directamente sobre el CECO de facturación siguen
   funcionando idéntico).
2. **Bucket (zona, línea)**: si no, se toma la clave `tk = (id_zone, id_line)`
   del CECO de la línea (del catálogo `cost_centers`); se agregan los
   ingresos (y el AR) por bucket `(zona, línea)` = Σ de **todos** los CECOs
   con esa misma `(id_zone, id_line)`. Si el bucket de ingreso tiene
   **exactamente un CECO generador** (un solo CECO con líneas de ingreso),
   la base es la de **ese CECO** (el "CECO de facturación" de la zona+línea).
3. **Sin fallback (regla 0)**: 0 CECOs generadores en el bucket, múltiples
   CECOs generadores (ambigüedad), CECO con `id_zone`/`id_line` NULL, o
   zona+línea sin facturación (ni recaudo/AR) presupuestada ⇒ base **0**.
   No hay fallback global ni por zona entera, ni error, ni exclusión
   (mismo espíritu de BR-VE-02).

**Clarificación B2** (`variable_receivables`): se resuelve con el MISMO
helper de B1, y la base toma el ingreso **del CECO RESUELTO**. **Componente
AR = 0 hoy (decisión del usuario 2026-10-20)**: la tabla `accounts_receivable`
NO tiene dimensión de CECO (ni el modelo, ni la tabla, ni el template
EstadoCuenta306090), por lo que atribuir AR a un `R_c(m)` es imposible sin
inventar datos; el intento previo de agrupar AR por `id_cost_center`
crasheaba con `AttributeError` en **toda** ejecución real (hallazgo durante
la validación de esta enmienda). Bajo la regla cero conservadora de
BR-VE-06, el término AR de B2c/E4c queda en 0 y se reactiva en cuanto la
carga de AR gane una columna de CECO. El AR global por mes se conserva para
los inflows del cash flow (fórmulas no variables, intocado).

Implementación: una sola query adicional de catálogo
(`cost_centers.id_cost_center, id_zone, id_line`, motor-scope, sin N+1);
los buckets `(zona, línea)` se derivan post-procesando los dicts
`income_ceco_by_month` / `ar_ceco_by_month` (dos passes de dict, sin joins
nuevos). Las claves de bucket son tuplas de **int** (`id_zone`, `id_line`);
un CECO con zona o línea NULL no participa de ningún bucket (solo la vía
propia quedará disponible para él).

**Nota de esquema (hallazgo de la validación, 2026-10-20)**: el intento
previo de espejo `ar_ceco_by_month[c][m]` (§6.1/§6.2) consultaba
`accounts_receivable.id_cost_center`, columna que NUNCA existió (modelo,
tabla real y template de carga coinciden) — ese código crasheaba con
`AttributeError` en cada `project_cash_flow` y en el liquidador IVA. Esta
enmienda corrige la query de AR a la forma global por mes de 02_02 §6
(cache global `balance` por `due_date` para los inflows) y establece el
término AR de B2c/E4c en 0 (ver §10.2, decisión del usuario).

### 10.3 Criterios de aceptación nuevos

| ID | Criterio |
|---|---|
| AC-BE24-8 | Línea variable sobre un CECO de **gasto** y facturación cargada sobre OTRO CECO de la MISMA (zona, línea) con exactamente un generador ⇒ monto = tasa × ingreso mensual del CECO de facturación (caso real 573: Despachos Costa Z1 KYLY, CECO 73, rate 2%, Enero 28 ⇒ base = ingreso Enero del CECO 151 = 8,445,800 ⇒ desembolso 168,916.00). |
| AC-BE24-9 | (Zona, línea) sin facturación presupuestada (0 generadores) ⇒ base 0 y desembolso 0, sin fallback global ni por zona, sin error. |
| AC-BE24-10 | (Zona, línea) con **más de un** CECO generador de ingreso ⇒ base 0 (ambigüedad conservadora, sin error). |
| AC-BE24-11 | E3/E4 del IVA espejo usan el MISMO helper de resolución que B1c/B2c (consistencia 1:1 entre `budgetEngine.py` y `budgetIvaEngine.py`). |

---

## 11. Enmienda A-02 — base de recaudo = entradas del flujo, sin término AR

> Fecha de la enmienda: **2026-10-21**
> Origen: decisión del usuario sobre la definición de "recaudo" en un
> presupuesto (escenario 573, BD dev).

### 11.1 Decisión (cita del usuario)

> "Como es un presupuesto, el recaudo debe estar basado en las ENTRADAS que
> están en el flujo, que sí tienen CECO."

### 11.2 Nueva base B2c / E4c (variable_receivables)

La base deja de ser `I_c(m) + AR_c(m)` (con el AR en 0 conservador desde la
A-01) y pasa a ser la **serie de entradas del Flujo** del propio
presupuesto:

```
R_c(m) = Σ projected_amount de líneas INCOME del presupuesto
         cuyo MES DE COBRO = month(COALESCE(payment_date, budget_date))
         cae en m, del CECO RESUELTO c (resolución A-01 §10.2 intacta:
         propio CECO primero, else bucket (zona, línea) con EXACTAMENTE un
         generador; si no ⇒ 0).
B2c: outflow(m) += Σ_v∈variable_receivables, m = v.budget_date.month   rate_v × R_c(m)
E4c: iva_v   = rate_v × R_c(m) × T      (emisión en v.budget_date, sin cambio)
```

* **Convención de años del mes de cobro** (cuadrada con la *Vista Flujo* del
  frontend: `cfMonth(line) = monthIndexOf(payment_date || budget_date)` +
  `outOfYearBucketOf(line, scenarioYear)`): la serie se filtra por
  `extract(year, COALESCE(payment_date, budget_date)) == budget_year`. Es
  decir, la cobranza de la facturación de **diciembre de N** que vence en
  **enero de N+1** alimenta la base de **N+1**, NO la de N — igual que esa
  línea cae en el bucket *out-of-year* ("after") de la view y no en la
  columna Ene de N. (Divergencia intencional documentada R-1 de
  frontend.03_04: los ingresos por `budget_date` del motor de inflows
  global de `project_cash_flow` NO cambian — 02_10 se reserva.)
* **Mes de causación**: sigue siendo el mes de `budget_date` de la línea
  variable (la comisión del mes `m` cae en el mes de su línea `m`;
  BR-VE-01 intacto). Solo cambia el MES DE LA BASE.
* **Base neta, sin IVA gross-up (asunción)**: el `× (1 + TAX_RATE)` de los
  inflows de `project_cash_flow` (BR de 02_02: `net × (1 + T)`) NO se
  aplica a la base: la comisión/recaudo se causa sobre el neto proyectado,
  igual que B1c. Documentado como asunción del negocio.
* **Término AR eliminado de la base** (contraste A-01→A-02): la A-01
  dejó el componente AR de `R_c(m)` en un 0 conservador "reactivable"
  cuando `accounts_receivable` ganara una columna de CECO. La A-02
  reinterpreta esa cláusula: la base YA NO ES `I + AR` y el AR — que no
  tiene dimensión de CECO (modelo, tabla y template EstadoCuenta306090
  coinciden) — abandona B2c/E4c con carácter permanente en esta fórmula.
  El AR global por mes de `due_date` se conserva SOLO para los inflows
  globales del cash flow engine (fórmulas no variables, intocado —
  02_02 §6/02_10).

Implementación: **una query adicional** en `project_cash_flow` (income
lines agregadas por `extract(month, coalesce(payment_date, budget_date))`
e `id_cost_center`, año filtrado sobre el mismo coalesce, budget_scope
aplicado) y **un dict pass en el loop de Q3** de `budgetIvaEngine._facts`
(mismo scan de líneas, cero SQL adicional). El espejo resultante
`cash_received_ceco_by_month[c][m]` NUNCA se agrega por bucket
`(zona, línea)`: como el resolver A-01 devuelve **un único CECO
generador**, el monto de ese CECO en el espejo de cobro ya ES el monto del
bucket — un segundo espejo de buckets sería código muerto. Los helpers de
`cecoBucketUtils.py` se usan tal cual (`build_ceco_buckets` ya era
parametrizable sobre cualquier espejo 12×CECO). Sin migraciones, sin
cambios de shape de API (NFR-1..NFR-4 de §7 intactos).

### 11.3 Criterios de aceptación nuevos

| ID | Criterio |
|---|---|
| AC-BE24-12 | Comisión `variable_receivables` de un CECO 73-type (resolución por bucket, línea v con `budget_date` Ene): base = **COBROS de Enero del CECO de facturación resuelto** Σ de entradas cuyo `month(payment_date || budget_date) = Ene`. Caso real 573: CECO 151 (facturación zona1/línea1) tiene facturación Ene = 8,445,800 con desplazamiento de pago; la comisión del CECO 8 (`variable_receivables` 8%, `budget_date` 2026-01-28) = `0.08 × R_151(Jan)` y **difiere** del valor A-01 (facturación, 675,664.00). Validado con los números reales de BD dev (ver §11.4). |
| AC-BE24-13 | `variable_sales` sigue en facturación por `budget_date` (B1c/E3c de la A-01, ajuste 2026-10-21 con año del mes de cobro NO aplicable): el CECO 73 despacho 2% Ene = 168,916.00 SIN cambio y el espejo E3/IVA no muta su base. |
| AC-BE24-14 | Facturación de dic-N con pago en ene-(N+1): NO alimenta la base B2c/E4c de Ene de N (año del coalesce == budget_year), cuadrando con el bucket out-of-year de la Vista Flujo. |

### 11.4 Validación real (BD dev, escenario 573 — 2026-10-21)

Ejecutada vía `docker exec crm_backend_dev python`. Año 2026. Todas las
cifras una única moneda COP; el desequilibrio cobro/facturación es el
desplazamiento de pago calendarizado (mismos términos de colección).

**Serie CECO 151 (000101, zona1/línea1) — facturación vs cobro por mes:**

| m | Facturación I (budget_date) | Cobro R (payment_date\|\|budget_date) |
|---|---|---|
| Ene | 8,445,800.00 | 6,334,020.00 |
| Feb | 3,528,200.00 | 0.00 |
| Mar | 15,473,200.00 | 13,073,940.00 |
| Jul | 2,205,400.00 | 35,304,340.00 |
| Dic | 26,602,700.00 | 125,401,870.00 |

(12 meses completos: difieren TODOS; p.ej. la facturación de Feb-2026 se
cobra totalmente fuera de Feb — parte en Ene con pago anticipado + parte
en Mar — y el Dic-2026 recauda 125M porque la facturación gigante de
Nov-2026 vence en Dic.) Queda confirmado el caso AC-BE24-14: la base de
dic-N = cobros del dic-N, no la facturación del dic-N; el término "dime
los números reales" de la AC se cumple con la tabla y el ejemplo siguiente.

**Comisión CECO 8 (210101, Comisiones zona1 KYLY, `variable_receivables`
8%, línea `budget_date` 2026-01-28, resuelve CECO 151):**

* ANTES (A-01, base facturación Ene): `0.08 × 8,445,800.00` = **675,664.00**
* AHORA (A-02, base cobro Ene): `0.08 × 6,334,020.00` = **506,721.60**
* Confirman que difieren (−168,942.40, debida al desplazamiento de pago)
  ⇒ AC-BE24-12 OK con datos reales.
* Otros meses reveladores de CECO 8: Feb-2026 = **0.00** (cobro 0) vs
  282,256.00 de facturación; Jul-2026 = **2,824,347.20** (cobro
  35,304,340) vs 176,432.00.

**Despacho CECO 73 (320101, `variable_sales` 2%, 28-ene) — SIN cambio
(AC-BE24-13)**: mantiene base de facturación = **168,916.00**.

**Caso revelador de la línea 4 de cada zona (CECOS 153/160/167/174/181 y
sus gastos `210x03`)**: la facturación de esa línea se concentra en
Ene/Abr/Jun/Sep/Nov y el cobro se desplaza, el espejo por cobro cambia el
patrón mensual (mismos totales anuales, distinto cuadro de meses). P.ej.
CECO 10 (`210103`, var_receiv 8%): A-01 siempre 0 salvo Jun=3,666,416.00
y Nov=8,735,232.00 (facturación); A-02 Abr=733,283.20, Jul=2,933,132.80,
Sep=1,747,046.40, Dic=6,988,185.60 (cuotas de pago de esas mismas
facturas). Los CECOs `210x04`–`210x07` (resolución None por 0
generadores) siguen en 0.
* `project_cash_flow(573)` corre completo E2E (12 filas `payment_month`
  1..12, sin errores; salidas de Feb-2026 caen de lo que daría la base de
  facturación porque el cobro de Feb es 0 — ver tabla). El liquidador IVA
  (`BudgetIvaEngine.settlement(573, 2026)`) también corre E2E.
