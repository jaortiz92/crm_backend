# Spec Backend: Créditos de financiación empresarial — calendario, presupuesto y flujo de caja

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S12-FINANCING-CREDITS` |
| **Spec counterpart** | FE: `frontend.03_16` (`FE-S16-FINANCING-CREDITS`) — consume los contratos de §9; bases: BE-S4/BE-S4D (`02_12`/`02_13`), BE-S9 P&L (`02_09`), BE-S10 cash flow (`02_10`), BE-S11 colaboradores (`02_21`) |
| **Tablas nuevas** | `financing_credits`, `financing_credit_installments`; v1 no captura pagos reales ni requiere tabla de pagos |
| **DDL requerido** | `create_all` solo crea tablas nuevas; sincronización manual de tablas `financing_*` existentes (§4.6) y migración independiente de `budget_lines` (§4.5/§11) |
| **Convenciones** | FastAPI, SQLAlchemy síncrono/PostgreSQL 16, Pydantic, `db.query`, `Decimal`, filenames camelCase, registro en submódulos `budget`; `app/main.py` sin cambios si el router budget sigue incluido |
| **Fecha** | 2026-10-09 |

---

## 1. Propósito y modelo conceptual

Registrar y proyectar **deuda financiera que la empresa debe** (préstamos, obligaciones financieras u otros créditos de financiación), con amortización de capital, intereses y seguro por vencimiento. Es un dominio distinto de los créditos actuales asociados a facturas/cartera. El modelo/API existente `credits` no se modifica, no se reutiliza y no es fuente de este motor.

```text
FinancingCredit (financing_credits; CECO de interés/seguro elegido al crear)
  └─ motor puro de amortización (francés: cuota fija | alemán: capital fijo)
       └─ FinancingCreditInstallment (una fila por período futuro)
            ├─ capital + fecha de pago → fuente única de cash flow
            ├─ interés + fecha de pago → fuente única de cash flow y BudgetLine expense para P&L
            └─ seguro + fecha de pago → fuente única de cash flow y BudgetLine expense para P&L

P&L: interés + seguro, nunca capital.
Cash flow: capital + interés + seguro desde el calendario activo de installments,
          cada uno por su fecha y exactamente una vez.
          La query de budget excluye source_engine='financing_credit'; las líneas
          de interés/seguro permanecen para budget/P&L, no son fuente de cash flow.
```

El sistema sigue el patrón del módulo de colaboradores: calendario proyectado persistido, trazable, reproducible e idempotente. La regeneración solo reemplaza artefactos propiedad del crédito afectado; conserva líneas manuales, líneas de colaboradores y cualquier otra fuente. No se crea vínculo ni sincronización automática con `payment_ledger`, `payable_ledger` ni otro payment ledger.

## 2. Alcance y exclusiones

**Incluye v1:** maestro de créditos nuevos y antiguos; captura del saldo de créditos antiguos a fecha de corte; selección de método francés o alemán; calendario futuro de capital/interés/seguro; asignación del CECO para interés y seguro; previsualización y persistencia del schedule; materialización de costos como gastos budgetarios; integración de capital/interés/seguro al cash flow desde el calendario activo; listado, detalle, desglose, regeneración idempotente y eliminación definitiva de un crédito mal registrado con todos sus calendarios/proyecciones.

**Fuera de alcance v1:** importación masiva de créditos antiguos (propuesta v1: captura manual; la importación se mantiene fuera hasta confirmación); pagos reales/conciliación con libros externos; abonos anticipados; período de gracia; tasas variables; reestructuración; monedas distintas de COP; créditos ligados a facturas; edición manual de cuotas generadas; cálculo de cronogramas pasados para créditos antiguos.

## 3. Registro de decisiones y pendientes

### 3.1 Confirmado por el usuario

| ID | Decisión confirmada |
|---|---|
| A-01 | Esta deuda de financiación es totalmente distinta de los créditos actuales ligados a facturas. |
| A-02 | `credits` y su API quedan intactos; el dominio utiliza modelo y rutas nuevos. |
| A-03 | Crédito antiguo: capturar saldo pendiente a una fecha de corte; desde el corte se calcula el calendario futuro. No reconstruir cuotas previas por defecto. |
| A-04 | Crédito nuevo: calcular calendario desde fecha de desembolso y condiciones originales. |
| A-05 | Al crear se selecciona uno de dos métodos: cuota fija (francés) o capital fijo (alemán). |
| A-06 | Interés y seguro se asignan al centro de costo seleccionado en el alta del crédito. |
| A-07 | El capital es salida de financiación y no gasto P&L. Intereses y seguros son gastos presupuestales. |
| A-08 | Cash flow incluye capital, intereses y seguros una sola vez desde el calendario activo y por fecha de cada componente, independientemente de `outflow_source`/escenario; interés y seguro también aparecen en budget/P&L. |
| A-09 | Persistencia y regeneración trazables e idempotentes, sin pisar líneas manuales ni artefactos de otros motores. |
| A-10 | COP en v1 y dinero calculado/almacenado con `Decimal` y `Numeric`; no usar `Float` en el motor ni en datos monetarios del feature. |
| A-11 | Frecuencia mensual por defecto y única soportada en v1; `day_count_convention='monthly_periodic'` por defecto y único valor soportado. `rate_convention` sigue siendo elección explícita (nominal o efectiva), sin inferir ni cambiar semántica de tasa. |
| A-12 | Crédito nuevo: `first_due_date` se deriva en backend como un mes calendario después del desembolso. La serie conserva el día ancla del desembolso (31-ene → 28/29-feb → 31-mar); crédito legacy debe indicar explícitamente su próximo vencimiento posterior al corte y ancla la serie en esa fecha. No se ajustan días inhábiles. |
| A-13 | Interés/seguro siguen el patrón de nómina: se simulan, sin escritura, en presupuestos `draft`/`closed` y se materializan idempotentemente solo en target(s) `active` al activarse. Los escenarios activos también son destinos válidos; capital nunca se materializa como gasto. |
| A-14 | Eliminar un crédito de financiación es una acción definitiva e irreversible, distinta de cerrar; aplica a créditos `active` y `closed`. En una transacción elimina primero solamente sus `BudgetLine` (`source_engine='financing_credit'`, `source_engine_id` de cualquier installment/revisión del crédito), después todos sus installments y el maestro. v1 no registra pagos reales; no tocar `credits` de facturas, pagos/ledgers, líneas manuales, otras fuentes ni artefactos de otro crédito. No requiere soft-delete ni cambio de esquema. |

### 3.2 Supuestos de trabajo / decisiones pendientes (no confirmadas)

| ID | Pendiente | Propuesta provisional para v1; requiere confirmación funcional antes de cerrar contratos productivos |
|---|---|---|
| OQ-02 | Convención de tasa anual nominal o efectiva | La API exige una elección explícita `nominal_annual` o `effective_annual`; no se establece default ni se infiere la convención de la tasa ingresada. El day-count ya está resuelto por A-11 como `monthly_periodic`. |
| OQ-03 | Seguro fijo por cuota o configurable | Provisionalmente monto COP fijo por cuota capturado en alta; hacer el cálculo aislado para sustituirlo por tarifa/regla cuando se decida. |
| OQ-04 | Pagos reales vs. calendario solamente proyectado | Provisional v1: el estado es `projected`; no existe marcado de pagado ni integración de pagos reales. Confirmar si se requiere entidad de pagos. |
| OQ-05 | Créditos antiguos masivos | Provisional v1: alta manual individual. Importación masiva fuera de alcance hasta confirmación. |
| OQ-06 | Abonos anticipados, gracia, tasa variable y reestructuración | Fuera del cálculo y edición de v1; definir posteriormente reglas para reamortizar saldo/plazo. |
| OQ-07 | Ajuste de días inhábiles | No se aplica ajuste bancario ni de día inhábil en v1 (A-12). La regla de ancla mensual y fin de mes queda confirmada en A-12. |
| OQ-08 | Presupuesto/escenarios múltiples | Resuelto siguiendo nómina: el presupuesto activo (incluido un target `is_scenario=True`) recibe líneas persistidas; cada draft/cerrado presenta el cálculo mediante `GET /budget/planning/{id_budget}/financing-simulation`, sin materializarlo. |

No presentar las propuestas pendientes como políticas aprobadas. La convención nominal/efectiva de cada crédito se selecciona explícitamente al crear; no hay interpretación silenciosa por parte del backend.

## 4. Datos, restricciones e integridad contable

### 4.1 `financing_credits` (nuevo; `app/models/budget/financingCredit.py`)

Campos mínimos propuestos:

| Campo | Tipo/restricción | Uso |
|---|---|---|
| `id_financing_credit` | integer PK | Identificador propio, sin relación con tabla `credits`. |
| `name` / `lender_name` | string, NOT NULL | Identificación legible de obligación/entidad financiera. |
| `credit_type` | string nullable | Clasificación libre y extensible; sin Enum PostgreSQL nuevo. |
| `status` | string, NOT NULL; `active/closed` | No implica registro de pagos reales. |
| `origin_type` | string NOT NULL; `new/legacy` | Distingue origen y validaciones. |
| `id_cost_center` | FK cost_centers NOT NULL | CECO elegido al crear; destino de intereses y seguro. |
| `method` | string NOT NULL; `french_fixed_payment/german_fixed_principal` | Método obligatorio, sin defaults silenciosos. |
| `currency` | string(3), NOT NULL, default `COP` | v1 valida exclusivamente COP. |
| `disbursement_date` | date nullable | Obligatoria para `new`; fecha de inicio contractual. |
| `original_principal` | `Numeric(15,2)` nullable | Obligatorio para `new`; principal desembolsado. |
| `cutoff_date` | date nullable | Obligatoria para `legacy`; saldo observado a esa fecha. |
| `opening_balance` | `Numeric(15,2)` NOT NULL | Para legacy: saldo pendiente capturado al corte; para new puede coincidir con principal inicial. |
| `annual_rate` | `Numeric(9,6)` NOT NULL | Tasa anual como fracción (p. ej. 0.18), junto con convención almacenada. |
| `rate_convention` | string NOT NULL | `nominal_annual`/`effective_annual`; elección explícita por crédito, sin default. |
| `day_count_convention` | string NOT NULL | Schema/API default `monthly_periodic`; Literal soportado único `monthly_periodic`, persistido para reproducibilidad. |
| `frequency` | string NOT NULL | Schema/API default `monthly`; único valor soportado en v1. |
| `term_installments` | integer NOT NULL CHECK > 0 | Número de períodos futuros. Para legacy significa cuotas restantes desde corte, no plazo original ya transcurrido. |
| `first_due_date` | date NOT NULL | En new: calculada por backend como un mes calendario tras desembolso. En legacy: captura requerida del próximo pago, estrictamente posterior a corte. |
| `insurance_per_installment` | `Numeric(15,2)` NOT NULL default 0 | Importe COP por cuota bajo el supuesto provisional OQ-03. |
| `schedule_revision` | integer NOT NULL default 1 | Incremento al regenerar por cambio de condiciones. |
| `created_at`, `updated_at` | datetime | Trazabilidad. |

Restricciones: montos no negativos; `opening_balance > 0`; tasa `>= 0`; plazo positivo; `currency='COP'`; `legacy ⇒ cutoff_date IS NOT NULL AND first_due_date explícita`; `new ⇒ disbursement_date IS NOT NULL AND original_principal IS NOT NULL`; `first_due_date > cutoff_date` en legacy. `frequency='monthly'` y `day_count_convention='monthly_periodic'` son los únicos valores admitidos. Índices por CECO, estado, fecha de corte y `origin_type`. Mantener nombres de enum como `String + Literal`, no Enum PostgreSQL.

### 4.2 `financing_credit_installments` (nuevo)

Una fila por período futuro, con desglose y fecha explícita para cada componente:

```text
id_financing_credit_installment Integer PK
id_financing_credit              Integer FK NOT NULL
installment_number               Integer NOT NULL CHECK > 0
period_start                     Date NOT NULL
period_end                       Date NOT NULL
principal_amount                 Numeric(15,2) NOT NULL CHECK >= 0
principal_due_date               Date NOT NULL
interest_amount                  Numeric(15,2) NOT NULL CHECK >= 0
interest_due_date                Date NOT NULL
insurance_amount                 Numeric(15,2) NOT NULL CHECK >= 0
insurance_due_date               Date NOT NULL
opening_balance                  Numeric(15,2) NOT NULL
closing_balance                 Numeric(15,2) NOT NULL CHECK >= 0
rate_used                        Numeric(9,6) NOT NULL
schedule_revision                Integer NOT NULL
projection_status                String(16) NOT NULL default 'projected'
created_at                       DateTime
UNIQUE(id_financing_credit, installment_number, schedule_revision)
```

Campos separados de vencimiento preservan la posibilidad de que capital, interés y seguro tengan calendarios distintos; con el supuesto mensual inicial pueden compartir fecha. En v1 no se asocia una cuota a una fila de `payment_ledger` ni se marca `paid`.

### 4.3 Precisión, redondeo y restricciones de dinero

- Motor, CRUD, modelos y schemas emplean Python `Decimal` y PostgreSQL `NUMERIC(15,2)` para COP; tasa `NUMERIC(9,6)`. Convertir entradas mediante `Decimal(str(value))`, nunca `Decimal(float)`.
- Redondear cada componente monetario a 2 decimales con `ROUND_HALF_UP`. Mantener precisión Decimal interna de al menos 12 decimales para interés/saldo antes de cuantizar cada cuota.
- Cuota final: ajustar principal por el saldo exacto restante tras redondeos; validar que saldo final sea `0.00` y que ninguna cuota cree saldo negativo ni principal total distinto del saldo de apertura por más de COP 0.01.
- No acumular cifras en `Float` ni usar `round()` de Python para dinero. Los response JSON pueden serializar como número decimal según convención existente, sin pérdida en persistencia ni motor.

### 4.4 Integridad de artefactos budget/cashflow

| Componente | Persistencia | P&L | Cash flow |
|---|---|---|---|
| Capital | Solo `financing_credit_installments.principal_amount` y `principal_due_date`; no `BudgetLine expense` | Excluido siempre | Añadido por cash-flow engine desde installments, exactamente una vez por `principal_due_date`. |
| Interés | Una `BudgetLine` `expense/fixed` por cuota con código `FIN_INTEREST` | Incluido como gasto | Añadido por cash-flow engine desde installments, exactamente una vez por `interest_due_date`; excluir su BudgetLine de la query budget de cash flow. |
| Seguro | Una `BudgetLine` `expense/fixed` por cuota con código `FIN_INSURANCE` | Incluido como gasto | Añadido por cash-flow engine desde installments, exactamente una vez por `insurance_due_date`; excluir su BudgetLine de la query budget de cash flow. |

Cada gasto tiene `id_cost_center` del crédito y su importe, `budget_date` (período de devengo presupuestario) y `payment_date` igual al vencimiento del componente. Los costos se materializan como filas independientes, jamás se consolidan capital+costos en un expense line.

`budget_lines.source_engine='financing_credit'`, `source_engine_id=id_financing_credit_installment`, `cost_component_code ∈ {FIN_INTEREST, FIN_INSURANCE}`. La identidad idempotente incluye `(id_budget, source_engine, source_engine_id, cost_component_code)`. Crear índice único parcial para `source_engine='financing_credit'` (sin afectar filas históricas). Estas líneas siguen siendo gastos de budget/P&L, pero la query de gastos budgetarios de cash flow debe excluirlas explícitamente con `source_engine IS DISTINCT FROM 'financing_credit'` (o predicado equivalente que también conserve filas históricas con origen NULL). La query de cash flow agrega capital, interés y seguro desde sus respectivos campos y fechas del calendario activo; no toma ninguno de estos tres componentes desde BudgetLine. Así se evita duplicar costos y se mantiene el calendario como fuente única de obligaciones de financiación incluso al cambiar escenario/presupuesto activo.

### 4.5 Compatibilidad de `budget_lines` y migración

Estado verificado: `budget_lines` ya posee `source_engine`, `cost_component_code`, y `projected_amount` es `Float`. El feature no debe agregar ni reutilizar columnas `id_collaborator` u otras específicas de colaboradores para asociar financiación.

Para identificación inequívoca del origen se propone `source_engine_id Integer NULL` (id de installment; polimórfico, integridad del origen en motor). Como `create_all` no añade columnas a tabla existente:

```sql
ALTER TABLE budget_lines
  ADD COLUMN IF NOT EXISTS source_engine_id integer;

CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_lines_financing_source
  ON budget_lines (id_budget, source_engine, source_engine_id, cost_component_code)
  WHERE source_engine = 'financing_credit';
```

Para honrar A-10 también en las líneas budgetarias materializadas, migrar `projected_amount` de `Float` a `NUMERIC(15,2)` con revisión de datos y backup:

```sql
ALTER TABLE budget_lines
  ALTER COLUMN projected_amount TYPE numeric(15,2)
  USING round(projected_amount::numeric, 2);
```

Antes de aplicar: snapshot/backup, verificar nulos/rangos y sumar diferencias de redondeo; cambiar el tipo SQLAlchemy y schemas a `Numeric/Decimal`; ejecutar regresión de P&L, cashflow, líneas e ingestas existentes. Migración manual explícita en despliegue; `create_all` no convierte el tipo. Esta conversión afecta la tabla compartida y es prerrequisito para afirmar Decimal de extremo a extremo; no reemplazarla por Float ni por ALTER a columnas históricas de colaboradores. Si el negocio no aprueba la conversión común, detener la materialización de líneas de interés/seguro hasta acordar un campo NUMERIC compatible con las lecturas existentes.

### 4.6 Sincronización manual de tablas de financiación existentes

Hallazgo de despliegue: `Base.metadata.create_all` crea las tablas que aún no existen, pero no altera tablas `financing_credits` o `financing_credit_installments` creadas con una versión anterior del modelo. Por tanto, la existencia de ambas tablas no garantiza que tengan el esquema actual; la creación/reintento del endpoint puede fallar al referenciar columnas nuevas, como `closure_date`, `closure_balance` o metadatos de installments.

La reparación manual, aditiva e idempotente está en `spec/migrations/2026-10-09_financing_credit_schema_sync.sql`. Añade `financing_credits.closure_date` y `closure_balance`, completa en installments las columnas faltantes `rate_convention`, `day_count_convention`, `method` e `id_cost_center`, hereda sus valores desde el crédito padre donde corresponda y establece `NOT NULL`. Agrega si faltan los checks de installments para convención de tasa, day count, método, CECO y estado de proyección; también agrega el check de estado de cierre del crédito y verifica el conjunto esperado de constraints, abortando si otras constraints están ausentes/no validadas o si los datos existentes las incumplen. La migración es transaccional y puede volver a ejecutarse; si hay cuotas huérfanas, faltan valores en el padre o los datos existentes violan constraints, aborta en vez de inventar o asignar datos artificiales. Corregir los datos reportados y volver a ejecutarla.

Si las tablas de financiación se crearon con una versión anterior, realizar y verificar un backup y aplicar esta migración antes de reintentar el endpoint de creación. Esta sincronización afecta únicamente las tablas de financiación y es independiente de la migración de `budget_lines` descrita en §4.5; no la sustituye ni incluye sus ALTER o conversión de tipo.

## 5. Fórmulas y motor de amortización

Servicio puro sugerido: `app/services/budget/financingCreditEngine.py`. Entrada: crédito persistido + método + parámetros capturados; salida: lista Decimal de cuotas futuras con componentes y fechas. No accede a HTTP ni confirma transacción. No calcula pagos anteriores al corte para legacy.

### 5.1 Tasa periódica y fecha

El valor mensual `i` depende de la convención de tasa explícita del crédito. El day-count soportado se limita a `monthly_periodic`:

```text
si nominal anual:    i = annual_rate / 12
si efectiva anual:   i = (1 + annual_rate)^(1/12) - 1
```

La fórmula efectiva usa potencia Decimal con precisión ampliada; no convertir a float. La convención de tasa no tiene default y debe ser elegida por quien crea el crédito. No se admite day-count por días en v1: schemas limitan `day_count_convention` al Literal `monthly_periodic`, que es también el default. Guardar `rate_convention` y `day_count_convention` en crédito y snapshot en schedule. No mezclar convenciones dentro de un crédito.

Fechas: frecuencia `monthly`. En `new`, backend deriva `first_due_date = disbursement_date + 1 mes calendario` y genera todas las fechas desde el ancla original del desembolso; así 31-ene → 28/29-feb → 31-mar y no se pierde el día 31 tras febrero. En `legacy`, el usuario debe suministrar el siguiente vencimiento tras `cutoff_date`; esa fecha funciona como ancla para las cuotas siguientes. Si el día ancla no existe en un mes, usar el último día calendario de ese mes. No se infiere ni aplica ajuste de día hábil.

### 5.2 Método francés — cuota fija

Para saldo inicial `P`, tasa periódica `i` y `n` cuotas restantes:

```text
si i = 0: cuota_base = P / n
si i > 0: cuota_base = P × i / (1 − (1+i)^(-n))
interés_k = saldo_apertura_k × i
capital_k = cuota_base − interés_k
saldo_cierre_k = saldo_apertura_k − capital_k
```

Cuota base incluye capital+interés; seguro queda fuera de la cuota financiera y se añade como componente separado. Cuantizar interés y capital por cuota; en la última cuota fijar capital al saldo de apertura restante y calcular interés según convención, de modo que saldo cierre sea cero. El pago total proyectado por fecha = capital + interés + seguro.

### 5.3 Método alemán — capital fijo

```text
capital_base = P / n
para k=1..n:
  capital_k = capital_base (última cuota = saldo de apertura residual)
  interés_k = saldo_apertura_k × i
  saldo_cierre_k = saldo_apertura_k − capital_k
  cuota_financiera_k = capital_k + interés_k
```

La cuota total decrece si tasa y seguro se mantienen fijos; no presentar como cuota fija. Seguro se suma por separado según el supuesto OQ-03; se conserva como componente distinto en el schedule.

### 5.4 Control de redondeo y pseudocódigo

```text
P = Decimal(opening_balance).quantize(0.01, ROUND_HALF_UP)
saldo = P
cuota_base = formula_decimal(P, i, n)      # precisión ampliada
para k en 1..n:
    interes = quantize(saldo * interest_factor(k), 0.01, HALF_UP)
    capital = quantize(cuota_base - interes, 0.01, HALF_UP)  # francés
    # alemán: capital = quantize(P/n) salvo cuota final
    si k == n: capital = saldo
    exigir 0 <= capital <= saldo
    cierre = quantize(saldo - capital, 0.01, HALF_UP)
    seguro = insurance_rule(credit, k, due_date)             # provisional fijo
    persistir (capital, interes, seguro, vencimientos, saldo, cierre)
    saldo = cierre
assert saldo == Decimal('0.00')
assert abs(sum(capital_k) - P) <= Decimal('0.01')
assert sum(components) == sum(capital_k)+sum(interes_k)+sum(seguro_k)
```

Si una entrada produce una cuota francesa negativa, capital negativo, interés mayor al pago o schedule que no liquida, devolver 400 con motivo, no persistir parcialmente. Revisar casos `i=0`, `n=1`, fin de mes, residual de 0.01 y saldo legacy pequeño.

## 6. Flujos de alta y generación

### 6.1 Crédito nuevo

1. Usuario captura entidad acreedora/nombre, CECO, moneda COP, principal desembolsado y fecha, tasa anual y convención explícita, plazo de cuotas, seguro si aplica, y selecciona método francés o alemán. No captura primera fecha: backend la deriva como desembolso + un mes calendario. Frecuencia mensual y day-count mensual-periódico tienen default.
2. Validar `principal > 0`, tasa/plazo/fechas, CECO existente, COP, método permitido, fecha derivada posterior al desembolso y ausencia de condiciones fuera de alcance.
3. Fijar `opening_balance = original_principal`; generar cuotas desde desembolso/condiciones a partir de primer vencimiento y ninguna antes de éste.
4. Devolver preview generado por BE; en el mismo request de creación puede persistirse maestro + schedule + expenses (T-05, único commit) tras confirmación implícita del endpoint o el flujo preview→create debe enviar `schedule_revision`/hash para evitar diferencias.

### 6.2 Crédito antiguo

1. Capturar explícitamente saldo pendiente y fecha de corte, tasa/plazo restante y próximo vencimiento futuro, CECO, seguro y método elegido. La primera fecha futura sigue siendo obligatoria porque el corte no permite inferir el calendario. El monto ingresado es saldo de capital pendiente a corte, no monto original ni pago ya realizado.
2. No exigir ni generar cuotas anteriores a la fecha corte; no reconstruir historia bancaria ni cuotas pagadas. Mostrar metadatos originales opcionales como referencia sin usarlos para reconstrucción.
3. Validar primera fecha de vencimiento estrictamente posterior al corte. Calcular las cuotas restantes desde ese saldo y plazo restante; la cuota #1 del calendario es la primera posterior al corte.
4. Persistir `origin_type='legacy'`, `cutoff_date` y saldo capturado para auditoría. Importación Excel/masiva fuera de v1.

### 6.3 Regeneración idempotente

En alta/edición de condiciones/recalcular: bloquear la fila del crédito (o serializar por transacción), incrementar revisión; calcular schedule completo futuro; borrar/reemplazar solamente installments de ese crédito/revisiones activas y `BudgetLine` con `source_engine='financing_credit'` y source IDs pertenecientes a sus installments. No tocar gastos manuales, colaboradores, compras ni otro crédito. Validar source antes de borrar y hacer todos los cambios en una transacción atómica: o maestro+schedule+líneas quedan consistentes, o rollback completo.

### 6.3.1 Eliminación definitiva

`DELETE /budget/financing-credit/{id_financing_credit}` elimina permanentemente el crédito `active` o `closed` y todos sus installments de todas las revisiones. Es la eliminación de un registro mal capturado, no un mecanismo de cierre o pago. En una única transacción: (1) reunir IDs de todos los `FinancingCreditInstallment` cuyo `id_financing_credit` coincida; (2) borrar y contar exclusivamente las `BudgetLine` cuyo `source_engine='financing_credit'` y `source_engine_id` esté en ese conjunto, en todos los budgets; (3) borrar todos esos installments y el `FinancingCredit`; (4) confirmar una vez. Ante cualquier error se hace rollback total. Un ID de fuente NULL, manual, de otro engine o perteneciente a otro crédito no se borra; tampoco se toca el dominio `credits` asociado a facturas ni ningún payment ledger. No hay soft-delete ni tabla/columna/migración nueva. Respuesta 200: `{ "id_financing_credit": <id>, "budget_lines": <cantidad>, "installments": <cantidad> }`; ID inexistente (incluyendo segundo DELETE) responde 404.

Idempotencia por `id_financing_credit + installment_number + schedule_revision` para filas; por `(id_budget, source_engine, source_engine_id, cost_component_code)` para expense lines. Mismo input y revisión efectiva no duplica cuotas ni BudgetLines. Cambio de tasa, método, plazo, CECO o seguro solo reemplaza artefactos del crédito afectado. Mantener histórico de revisiones mínimo mediante revision/version metadata; si se exige auditoría completa inmutable, agregar historial dedicado como decisión implementativa, sin conservar cuotas obsoletas en la consulta activa.

### 6.4 Materialización de budget lines y P&L

- En alta/edición/recalculo, materializar por año exclusivamente en presupuesto(s) `status='active'`, permitiendo `is_scenario=True`; nunca persistir a presupuestos `draft` o `closed`. Cuando no haya target activo, conservar schedule y advertir que los costos se simulan en borradores y se materializan al activar una meta. Al activar target, `materialize_financing_for_scenario_year(db, year, id_budget)` corre después del commit de `set-target`, incluye el id activado y escenarios activos, e informa warnings sin revertir/fallar la activación.
- `GET /budget/planning/{id_budget}/financing-simulation` es una derivación pura para presupuestos no activos. Retorna exclusivamente cuotas de créditos/schedules activos con vencimiento dentro del año del budget, una línea por componente positivo `FIN_INTEREST` o `FIN_INSURANCE`, con CECO, fechas, monto y IDs de crédito/cuota. El total nunca incorpora principal. Budget activo responde 400 porque ya tiene líneas materializadas. La lectura no escribe ni repara datos.
- **BE-S12-CF-BUDGET (flujo del Grid de presupuestos):** `GET /budget/planning/{id_budget}/financing-principal-flow` es un stream separado, read-only y autenticado para que el flujo client-side del editor incluya capital sin convertirlo en gasto. Verifica que exista el budget (404 si no); acepta cualquier estado `active`, `draft` o `closed`. Responde `{id_budget, budget_year, total_principal, lines}` leyendo todos los installments `projection_status='projected'` de créditos `status='active'`, solo para `schedule_revision` actual y `principal_amount > 0`. Incluye **todos** los vencimientos, aunque `principal_due_date` caiga antes o después de `budget_year`, para que el cliente construya buckets fuera de año. Cada línea es `{month, payment_date, id_cost_center, amount, id_financing_credit, installment_number, description}`, con `month=YYYY-MM` de `payment_date`; `total_principal` es la suma de todas las líneas retornadas. No incluye interés ni seguro (ya están como expense materializados en budget activo o se derivan desde `financing-simulation` en otro presupuesto), no escribe/actualiza `budget_lines` y no muta schedules.
- Al serializar un crédito, en ausencia de target activo devolver warning informativo de simulación y activación; no solicitar regenerar para mostrar costos de borrador. Si hay target activo y le faltan líneas esperadas de la revisión activa, reportar warning de inconsistencia/recalculo. La serialización es solo lectura.
- `line_type='expense'`, `behavior_type='fixed'`, `id_cost_center=credit.id_cost_center`, `budget_date=period_end` (mes presupuestario de la cuota), `payment_date=due_date` del componente, `projected_amount=Decimal`, descripción con acreedor, componente y cuota; `has_iva` según regla existente por defecto/compatibilidad (no inferir tratamiento tributario nuevo; confirmar si gasto incluye IVA antes de customizar).
- Capital no es `BudgetLine`, no entra a expense ni a P&L. No materializar capital como línea de gasto ni crear total agregado que mezcle componentes.
- El P&L existente no requiere sumar installments ni lógica específica: recibe interés/seguro a través de `budget_lines` expense. Verificar que filtro por `line_type='expense'` cuente cada línea una vez. `source_engine` es solo trazabilidad, no exclusión de P&L.

### 6.5 Integración de cash flow (anti doble conteo)

Extender `BudgetEngine.get_cash_flow()` (spec `backend.02_10`, ruta ya existente `GET /budget/analytics/cash-flow`) con agregados del calendario activo de `financing_credit_installments`: `principal_amount` por `principal_due_date`, `interest_amount` por `interest_due_date` e `insurance_amount` por `insurance_due_date`, para fechas de ventana proyectada. La query selecciona solo filas de la revisión activa de cada crédito, nunca revisiones obsoletas; agrega cada componente por separado para respetar vencimientos distintos. Los tres componentes son salidas de caja con la convención negativa del payload (`outflows <= 0`). No se toma ninguno de ellos desde BudgetLine.

La query presupuestaria existente (Q5) mantiene sus fuentes budget/AP y sus reglas actuales, pero debe excluir explícitamente `budget_lines.source_engine='financing_credit'` de los gastos que alimentan cash flow. Esas líneas permanecen intactas para presupuesto y P&L. Así el cash flow no depende del presupuesto/escenario donde se materializó una línea ni pierde costos al cambiar de escenario:

```text
cashflow_outflow = existing_budget_and_ap_sources  # excluir budget_lines.source_engine='financing_credit'
                 + financing_installments.principal_amount por principal_due_date
                 + financing_installments.interest_amount por interest_due_date
                 + financing_installments.insurance_amount por insurance_due_date
```

No sumar una cuota total ni leer los mismos tres componentes de otra fuente. Deduplicación explícita: agregar cada columna monetaria desde installments con su fecha correspondiente; excluir de Q5 todas las `BudgetLine` con `source_engine='financing_credit'`; evitar joins que multipliquen installments. Aplicar a cada componente el filtro de fechas/cutoff de la ventana proyectada; no agregar importes vencidos antes del inicio de proyección/cutoff sin definir política nueva; publicar conteo/monto fuera de ventana solo si contrato analítico lo necesita. La financiación se agrega siempre, exactamente una vez, independientemente de `outflow_source`: dicho parámetro continúa controlando las fuentes existentes budget/AP y no suprime obligaciones de financiación. Esta regla aplica a todas las consultas de escenario/presupuesto; el calendario activo no se reasigna ni se duplica por cambios de escenario. No deduplicar contra `credits`, AP o ledgers; no existe enlace automático.

El cashflow es analítico de solo lectura; esta extensión no escribe resultados ni muta el ledger. El P&L queda inalterado para capital, y cash flow nunca contabiliza capital como expense.

## 7. Schemas Pydantic sugeridos

`app/schemas/budget/financingCredit.py`, export nombrado en `app/schemas/budget/__init__.py` y `app/schemas/__init__.py` cuando corresponde:

- `FinancingCreditCreate`: datos comunes + `origin_type`, inputs new o legacy discriminados, método requerido, Decimal COP, CECO, condiciones/tasa/seguro; frecuencia default `monthly`, day-count default Literal `monthly_periodic`; `first_due_date` omitible solo en `new` y derivada por backend, obligatoria en `legacy`.
- `FinancingCreditUpdate`: solo condiciones editables; nunca editar cuotas/artefactos individualmente. Cambios disparan regeneración transaccional.
- `FinancingCreditOut`/`FinancingCreditListResponse`: maestro, `schedule_revision`, resumen de saldo/cuotas, totales futuros por componente y warnings de materialización; montos Decimal.
- `FinancingInstallmentOut`: número/período, saldo inicial/final, principal/interés/seguro, tres vencimientos, totales derivados backend, status proyectado.
- `FinancingSchedulePreview`: crédito/condiciones normalizadas, método, convención, lista installments, totales por componente y validaciones. FE nunca ejecuta fórmulas.
- `FinancingRecalculateRequest/Result`: id (path), opcional periodo inicial solo si se define con seguridad; contadores `replaced_installments`, `created_installments`, `replaced_budget_lines`, `created_budget_lines`, warnings.
- `FinancingSimulationOut` para `GET /budget/planning/{id_budget}/financing-simulation`: `{id_budget, budget_year, financing_credits_count, total_interest, total_insurance, total_annual_expenses, lines}`. Cada línea tipada contiene `{month, budget_date, payment_date, id_cost_center, cost_component_code, component_name, description, amount, id_financing_credit, id_financing_credit_installment}`; el componente solo puede ser `FIN_INTEREST` o `FIN_INSURANCE`, y los importes/totales son `Decimal`.
- `FinancingPrincipalFlowOut` / `FinancingPrincipalFlowLine` para `GET /budget/planning/{id_budget}/financing-principal-flow`: `{id_budget, budget_year, total_principal, lines[]}`. Cada línea tipada contiene `{month, payment_date, id_cost_center, amount, id_financing_credit, installment_number, description}`; monto y total son `Decimal`. Las fechas pueden caer fuera del año presupuesto; no exponer campos de interés/seguro en este contrato.
- Para `cash-flow`: ampliar `CashFlowMeta` con datos aditivos por componente de financiación (`financing_principal`, `financing_interest`, `financing_insurance` y conteo de installments) o `sources.financing_*`; `time_series` shape existente no rompe consumidores. No exponer schedules enteros desde cash flow.

Montos COP y tasas usar Decimal/Pydantic `Decimal`; restricciones de `Literal` para métodos, origen y estado.

## 8. Organización de implementación y registro

| Punto | Archivos sugeridos |
|---|---|
| Modelos | `app/models/budget/financingCredit.py` → imports explícitos en `app/models/budget/__init__.py`; dos clases nuevas. |
| Líneas existentes | `app/models/budget/budgetLine.py`: `source_engine_id` nullable y `projected_amount Numeric`; no reusar columnas de colaboradores. |
| Schemas | `app/schemas/budget/financingCredit.py`; import nombrado en `app/schemas/budget/__init__.py` y `app/schemas/__init__.py`. Actualizar tipo decimal de línea budget si se ejecuta migración. |
| CRUD | `app/crud/budget/financingCredit.py` con `Session` primero y query legacy; exportar por patrón `from .financingCredit import *` en `app/crud/budget/__init__.py`. |
| Servicio | `app/services/budget/financingCreditEngine.py` (puro para fórmulas); servicio de aplicación/materialización en el módulo budget. |
| API | `app/api/budget/financingCredit.py`, `APIRouter()`; registrar import y `include_router` en `app/api/budget/__init__.py`. |
| Cash flow | `app/services/budgetEngine.py` + schemas/API analítica para sumar los tres componentes desde el calendario activo, excluir líneas financing_credit de Q5 y exponer meta de fuente, según §6.5. |
| P&L | Sin suma nueva: verificar inclusión de expense lines de intereses/seguros; proteger exclusión de capital. |

No modificar `app/main.py` si el router raíz `budget` sigue incluido allí. En `app/api/budget/__init__.py` registrar el subrouter y todos sus paths literales antes de `budget_router`: la ruta legacy `/budget/{id}` puede capturar dos segmentos y responder 422 si se monta antes. Debe ser consistente con el orden observado para colaboradores. Rutas nuevas bajo prefijo `/budget/financing-credit` sin slash final, como el resto del submódulo.

## 9. API sugerida

Todas requieren JWT (`get_current_user`) y usan DB síncrona. Solo roles autorizados para edición financiera mutan; reutilizar el mecanismo de permisos de budget existente o definir allow-list de roles con nombres acordados, sin asumir nombres no verificados.

| Método/ruta | Contrato y comportamiento |
|---|---|
| `GET /budget/financing-credit` | Filtros `q`, `id_cost_center`, `status`, `origin_type`, `page`, `size`; retorna `{total, items}` con totales proyectados. |
| `POST /budget/financing-credit/preview` | Valida condiciones new/legacy y devuelve schedule BE sin persistir. No crea presupuesto lines. |
| `POST /budget/financing-credit` | Crea maestro, cuotas y gastos asociados de forma atómica; alternativamente requiere hash/version de preview si interfaz separa preview y alta. |
| `GET /budget/financing-credit/{id}` | Detalle maestro + cuotas activas + resumen; route literal `/preview` se monta antes de `/{id}`. |
| `PUT /budget/financing-credit/{id}` | Cambiar condiciones permitidas y regenerar solo artifacts del crédito; no aceptar componentes de cuotas generadas ni `source_engine` arbitrario. |
| `GET /budget/financing-credit/{id}/schedule` | Calendario futuro, paginado/filtro por rango, montos por componente y status proyectado. |
| `POST /budget/financing-credit/{id}/recalculate` | Regeneración idempotente completa para crédito. |
| `POST /budget/financing-credit/{id}/close` | Cierre administrativo sin inventar pago real; define corte y suspende cuotas futuras solo cuando se capture nuevo saldo/condición explícita. No cerrar con eliminación destructiva. |
| `DELETE /budget/financing-credit/{id}` | Eliminación permanente e irreversible para estado `active` o `closed`: borrar primero solo BudgetLines engine-owned de todos los IDs de installment/revisiones del crédito; luego todos sus installments y el crédito; commit/rollback único. Retorna `{id_financing_credit, budget_lines, installments}`; inexistente/segundo delete → 404. No registrar ni modificar pagos reales, `credits` de facturas, manuales, otras fuentes o filas de otros créditos. |
| `GET /budget/planning/{id_budget}/financing-simulation` | Simulación read-only de interés/seguro del año en draft/closed; 400 si el budget está activo. Respuesta exacta: `{id_budget, budget_year, financing_credits_count, total_interest, total_insurance, total_annual_expenses, lines[]}`. Cada línea: `{month, budget_date, payment_date, id_cost_center, cost_component_code, component_name, description, amount, id_financing_credit, id_financing_credit_installment}`; componentes exclusivamente `FIN_INTEREST`/`FIN_INSURANCE`, sin capital. |
| `GET /budget/planning/{id_budget}/financing-principal-flow` | JWT, read-only, sin restricción por status del budget; 404 si no existe. Entrega el capital projected `>0` de todos los vencimientos de créditos activos y revisión activa, incluyendo fechas fuera de `budget_year`: `{id_budget, budget_year, total_principal, lines[]}`. Línea: `{month, payment_date, id_cost_center, amount, id_financing_credit, installment_number, description}`; `month` deriva de `payment_date`. Excluye interés/seguro, no crea/muta `budget_lines`; nunca es expense/P&L. |

Pagos reales no se incluyen en v1 provisional (OQ-04); no exponer endpoint `/payment` ni vincular a ledgers hasta decisión. Versionar API solo si hay consumidor externo (no necesario para las rutas sugeridas).

## 10. Permisos, validación y errores

| HTTP | Caso |
|---|---|
| 400 | COP inválido, corte sin saldo/plazo restante, tasa/conversión inválida, cuotas que no amortizan, condición fuera de alcance. Mensaje estructurado `{message, field?, code?}`. |
| 401/403 | JWT ausente o rol sin permiso de consulta/edición. No revelar datos de deuda en errores de acceso. |
| 404 | Crédito, CECO o presupuesto destino referenciado inexistente. |
| 409 | Conflicto de edición/revisión concurrente, schedule version obsoleta, duplicación de clave natural definida por negocio. |
| 422 | Formato/date/Decimal/Literal inválido según FastAPI/Pydantic; también ausencia de campos requeridos por `origin_type` o vencimiento legacy `<= cutoff`. |
| 500 | Fallo inesperado; rollback total, log de request/user/crédito sin credenciales ni payload financiero completo. |

Crear/listar/detalle/desglose con protección coherente con datos financieros internos. La regla de roles concreta es pendiente de integración RBAC: no tratar un error 403 como ausencia de datos.

## 11. Despliegue y compatibilidad

Fases de despliegue requeridas porque Postgres usa `Base.metadata.create_all` sin migraciones automáticas:

1. Revisar backup, suma/rango/escala de `budget_lines.projected_amount`, ambientes y código dependiente; preparar ventana de mantenimiento para conversión `NUMERIC`.
2. Si las tablas `financing_*` ya existen y fueron creadas con una versión anterior del modelo, hacer/verificar backup y ejecutar `spec/migrations/2026-10-09_financing_credit_schema_sync.sql` antes de reintentar el endpoint de creación (§4.6). `create_all` no actualiza esas tablas; la migración sincroniza `closure_date`, `closure_balance` y columnas/checks faltantes de installments.
3. Por separado, ejecutar los ALTER manuales de `budget_lines`: `source_engine_id` nullable, conversión validada de `projected_amount` y creación del índice parcial único (§4.5), antes de servir código que espera esos cambios. Aplicar con backup y validación de filas previo/posterior; esta migración de budget no forma parte de la reparación `financing_*`.
4. Desplegar modelos/schemas/servicios; verificar que enums actuales de `line_type` conservan valores vigentes. No agregar enum Postgres para método u origen.
5. Smoke de P&L/cashflow/lectura y escritura de una fila, asegurar valores viejos iguales con tolerancia máxima 0.01 por efecto explícito de conversión/redondeo. No backfill de `source_engine_id`; NULL en todos los gastos antiguos.
6. Habilitar alta conforme selección explícita de `rate_convention` en cada crédito; el day-count queda fijado en `monthly_periodic`. `create_all` después puede permanecer como creación idempotente de tablas nuevas.

La API vieja `/budget/credits` (si existente) y tabla `credits` no cambian. Líneas y esquemas aditivos; filas antiguas continúan con `source_engine_id=NULL`; proyecciones existentes permanecen legibles. No añadir columnas/valores a la familia collaborator ni cambiar su motor.

## 12. Requisitos no funcionales

| ID | Requisito |
|---|---|
| NFR-BF-1 | Dinero en motor y DB `Decimal/Numeric`, COP a 2 decimales; tasa Decimal; cero `Float` en fórmulas/persistencia del feature. |
| NFR-BF-2 | Alta/regeneración transaccional: rollback completo ante error; sin schedule parcial ni huérfanos de BudgetLine. |
| NFR-BF-3 | Idempotencia por crédito/revisión/período y por id de installment/componente en expense lines; dos regeneraciones iguales producen exactamente mismo schedule y conteos. |
| NFR-BF-4 | Regenerar un crédito no cambia filas manuales, colaboradores, otras fuentes ni créditos. Auditabilidad por origen, revisión, usuario/fechas. |
| NFR-BF-5 | Cash flow usa el calendario activo como fuente única de capital/interés/seguro por sus fechas; excluye explícitamente las budget lines financing_credit de su query budget, sin depender de `outflow_source` ni escenario; ningún hook automático al payment ledger. |
| NFR-BF-6 | Backward compatible con consumidores actuales; ruta estática ordenada antes de `/budget/{id}`; `app/main.py` sin cambio si router budget está montado. |
| NFR-BF-7 | Soportar al menos 1.000 créditos × 360 períodos con listado paginado y carga de schedule acotada; generación de 360 cuotas < 500 ms/crédito en entorno de aplicación excluyendo DB/HTTP. |
| NFR-BF-8 | Registrar convención de tasa, day-count, origen, fecha de corte y revisión para reproducir cualquier cuota; no guardar secretos bancarios. |

## 13. Criterios de aceptación cuantificables

1. **AC-BF-1 separación:** crear legacy/new solo toca tablas `financing_*` y sus dos componentes de gasto; `credits` y sus filas/contratos quedan byte-a-byte intactos.
2. **AC-BF-2 cutoff legacy:** saldo capturado COP 1.000.000, corte 2026-03-15 y primera fecha 2026-04-15 ⇒ ninguna cuota/interés/seguro con vencimiento anterior o igual al corte; suma de capital futuro = 1.000.000.00 ± 0.01.
3. **AC-BF-3 nuevo:** principal se amortiza desde desembolso; backend normaliza primer vencimiento a desembolso + un mes calendario y no hay cuota anterior al desembolso. `origin_type=new` requiere desembolso y principal.
4. **AC-BF-4 métodos:** tasa cero, principal 1.200.000 y 12 períodos ⇒ ambos métodos capital totaliza exactamente COP 1.200.000.00; francés tiene cuota financiera fija con ajuste máximo 0.01 al final; alemán capital mensual COP 100.000.00 y saldo decreciente.
5. **AC-BF-5 interés:** con saldo P y factor i fijados por convención aceptada, cada período cumple interés = saldo apertura × factor de período, ROUND_HALF_UP a COP 0.01; saldo final es 0.00 y no hay capital negativo.
6. **AC-BF-6 seguro:** cada installment muestra valor y fecha independientes; el total de seguro coincide con la regla configurada; costo va al CECO seleccionado al alta.
7. **AC-BF-7 contabilidad:** para una cuota de capital 900.000, interés 80.000 y seguro 20.000, gasto P&L = 100.000 (no 1.000.000); `budget_lines` contiene solo dos gastos por monto 80.000/20.000 y fechas de pago correspondientes.
8. **AC-BF-8 cashflow sin duplicar:** para la misma cuota, cashflow reduce caja exactamente 1.000.000 una vez (principal 900.000, interés 80.000 y seguro 20.000, todos desde el calendario activo y cada uno por su fecha). La query budget excluye `source_engine='financing_credit'`; ni `outflow_source=ap` ni cambiar/reasignar escenario suprime o duplica las obligaciones de financiación. Las budget lines de interés/seguro permanecen en budget/P&L; no se agregan 1.100.000 ni 1.200.000.
9. **AC-BF-9 idempotencia y simulación:** generación/regeneración no duplica líneas en target activo; una línea manual y otra fuente quedan intactas. Con solo draft/closed, create/update/recalculate no persiste `BudgetLine`, el endpoint de simulación devuelve interés/seguro, fechas, CECO y montos sin writes y excluye principal. Activar una meta materializa idempotentemente las líneas; se admiten targets activos scenario.
10. **AC-BF-10 flujo de capital por presupuesto:** el smoke consulta `financing-principal-flow` con budget `draft` y fixture de installments antes/dentro/después del año. Devuelve todos los vencimientos con mes según fecha de pago, ignora revisión obsoleta, crédito cerrado, cuotas suspendidas y principal cero; cada capital de la revisión activa aparece una sola vez. Consultar budgets `active`/`closed` entrega la misma fuente. La lectura no modifica budgets, schedules ni `budget_lines`, y el contrato no contiene interés/seguro.
10. **AC-BF-10 aislamiento:** cambiar condiciones del crédito A reemplaza solo A; todas las cuotas/líneas de crédito B, colaboradores, manuales y tablas reales siguen idénticas.
11. **AC-BF-11 COP:** entradas Float-like se normalizan desde string Decimal; motor carece de float; suma SQL Numeric coincide con response en centavos; `projected_amount` antiguo conserva valores/redondeo según plan de migración aprobado.
12. **AC-BF-12 API/rutas:** OpenAPI expone `/budget/financing-credit` y `preview`; paths literales responden al router nuevo (no los captura `/budget/{id}`); `DELETE /budget/financing-credit/{id}` no interfiere con schedule ni con router legacy; sin editar `app/main.py` mientras router padre esté incluido.
13. **AC-BF-13 rollback:** error de parámetros/materialización a mitad de request deja sin cambios crédito, installments y líneas.
14. **AC-BF-14 cutoff y fechas:** falta de `first_due_date` o fecha `<= cutoff` en legacy devuelve 422 y cero escrituras; plazo/fechas insuficientes devuelve error útil y no reconstruye cuotas anteriores. Para desembolso 2026-01-31, preview y alta devuelven vencimientos 2026-02-28 y 2026-03-31 con primer vencimiento normalizado igual.
15. **AC-BF-15 eliminación:** active y closed pueden borrarse definitivamente; borrar elimina líneas financieras asociadas a installments de todas las revisiones/budgets primero, luego installments y maestro, devuelve conteos y un segundo DELETE responde 404. Líneas manuales, otros engines, IDs de otro crédito, el otro crédito, el dominio `credits` y pagos/ledgers permanecen idénticos. Una falla luego de borrar/flushear líneas revierte la transacción completa; `close` conserva su comportamiento distinto.

## 14. Estrategia de pruebas

No hay suite global existente. Al implementar, cubrir:

1. Pruebas unitarias del motor puro para francés/alemán, tasa cero/no cero, último período, períodos mensuales de fin de mes (incluyendo ancla 31-ene → 28/29-feb → 31-mar), precisión, sumatorias y fechas; usar `Decimal`, asserts centavo a centavo. Verificar defaults monthly/monthly_periodic.
2. Pruebas de workflow de new y legacy: primer vencimiento new derivado e igual entre preview/persistencia; próximo vencimiento legacy explícito y posterior al corte; ninguna fila pasada; casos invalid input, round-trip de revisión, rollback.
3. Pruebas de materialización y simulación: unicidad de `(budget, engine, installment, component)`, reemplazo acotado, líneas manuales/otras fuentes intactas y monto/source/component/CECO/fechas correctos; en draft/closed verificar simulación read-only y cero escrituras; verificar hook post-commit, warning-only e idempotencia al activar target, incluyendo scenario activo.
4. Integración de cashflow con fixture determinístico: calendario activo aporta principal/interés/seguro por fechas independientes; query budget excluye `source_engine='financing_credit'`; asserts total = suma de los tres una vez con `outflow_source=budget` y `ap`, cambios de escenario y revisiones históricas presentes, además de cutoff/rango/signos conforme `backend.02_10`.
5. Regresión de P&L: gastos financieros entran una vez en Expenses; capital no altera P&L; benchmark previo/post migración para categorías existentes.
6. Prueba de migración Postgres 16 desde DB existente: `create_all` solo crea tablas; ALTER manual crea columna/index y cambia Float→Numeric; antiguos NULL para origen nuevo; lecturas/CRUD actuales ejecutables.
7. Smoke JWT/OpenAPI/routing en backend dev :8003 y regresión a `/budget/analytics/cash-flow`, P&L y endpoints `/budget/{id}`.
8. Smoke de eliminación sobre crédito con varias revisiones y BudgetLines en distintos budgets; comprobar alcance exacto de `source_engine`/IDs, preservación de manuales/otros engines/otro crédito, eliminación active y closed, doble DELETE 404 y rollback inyectando un fallo dentro de la transacción. No conectar a DB real ni modificar esquema.

## 15. Riesgos, dependencias y trazabilidad

| ID | Riesgo/dependencia | Mitigación |
|---|---|---|
| DEP-BF-1 | Convención efectiva/nominal cambia el importe de interés. | Exigir elección explícita por crédito, persistirla y presentarla al usuario; no establecer una semántica silenciosa. Day-count único `monthly_periodic`. |
| DEP-BF-2 | `projected_amount` es `Float` legacy, no satisface A-10 al materializar gasto. | Conversión manual a Numeric y regresión amplia; decisión de plataforma requerida (§4.5/§11). |
| DEP-BF-3 | Costos proyectados requieren target activo para materialización; borradores no contienen líneas físicas. | GET de simulación presenta costos en draft/closed sin escritura; activation hook materializa en target activo y advierte errores sin fallar set-target. |
| RSK-BF-1 | Cash flow puede confundir capital/expense, duplicar costos o perder pagos al cambiar `outflow_source`/escenario. | Calendario activo único por componente y fecha, exclusión explícita de líneas financing_credit en Q5, pruebas AC-BF-7/8 y métrica/meta de fuente. |
| RSK-BF-2 | Los cambios de scenario no modifican obligación financiera global. | OQ-08 visible en producto; confirmar si se requiere forecast scenario específico. |
| OQ-BF-3 | Regla de seguro y pagos reales aún no cerradas; no se ajustan días inhábiles en v1. | Mostrar pendientes en FE; no simular pagos ni reglas de calendario escondidas. |

Trazabilidad: A-01/A-02 → §1/§11; A-03/A-04 → §6.1/6.2; A-05 → §5.2/5.3; A-06 → §4.4/6.4; A-07/A-08 → §4.4/6.4/6.5 y AC-BF-7/8; A-09 → §6.3 y AC-BF-9/10; A-10 → §4.3/4.5 y AC-BF-11. Contraparte FE: `crm_frontend/spec/frontend.03_16_Spec_frontend_budget_financing_credits.md` consume contratos de §7–§9.
