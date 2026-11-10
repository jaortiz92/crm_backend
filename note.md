# Notas de despliegue — CRM Backend (DDL manual sin Alembic)

El proyecto usa `Base.metadata.create_all`, que **solo crea tablas nuevas**:
nunca añade columnas a tablas existentes y **nunca agrega valores a un tipo
enum existente**. Toda acción de esquema sobre objetos ya creados debe
ejecutarse manualmente (autocommit `psql -c`) **ANTES** de desplegar el
código que la consume. Checklist de deploy: ALTER → deploy.

## 1. Precedente — `budgets.include_carryover` (BE-S6-CARRYOVER, backend.02_16 §3.2)

```sql
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS include_carryover BOOLEAN NOT NULL DEFAULT FALSE;
```

- Columna de preferencia del escenario para el arrastre N−1→N.
- `create_all` no la agrega: sin el ALTER, todo `GET` sobre `budgets` falla
  con `UndefinedColumn` al desplegar el modelo nuevo.

## 2. `linetypeenum` += 'PURCHASE' (BE-S8-BUDGET-PURCHASES, backend.02_18 §3.3)

```sql
ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';
```

- **APLICADO EN DEV el 2026-09-15** (se perdió al restaurar la BD desde dump;
  **re-aplicado el 2026-09-18** con la migración §3) vía
  `docker exec db_crm_dev psql -U postgres -d crm -c "ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';"`.
  Verificación: `SELECT unnest(enum_range(NULL::linetypeenum));` ⇒
  `INCOME | EXPENSE | PURCHASE`.
  (Ojo: la verificación literal de la spec usaba `unn(...)` — la función
  correcta de Postgres es `unnest(...)`.)
- El tipo Postgres almacena los **NAMES** de los miembros del enum Python
  (mayúsculas: `'INCOME'`, `'EXPENSE'`, `'PURCHASE'` — evidenced en
  `budget_lines.line_type`); SQLAlchemy resuelve el bind por nombre-then-
  valor, por eso el código filtra con `== "income"` y funciona.
- PG 16: `ADD VALUE` no puede correr dentro de una transacción que luego
  use el valor — usar `psql -c` (autocommit), igual que el precedente.
- Tercer valor de `LineTypeEnum` = línea de COMPRA (importación):
  `budget_date` = fecha de importación, `payment_date` SIEMPRE NULL (las
  cuotas al proveedor se derivan en lectura desde `line_payable_terms`,
  NFR-BE8-1). Todos los consumidores existentes filtran por igualdad
  exacta `'income'`/`'expense'`, así que `purchase` queda fuera
  automáticamente del P&L / cash-flow / listing (spec §3.4); el único
  filtro ciego (`get_carryover_lines`) quedó blindado con el guard
  BR-CO-12.
- **PENDIENTE EN PRODUCCIÓN:** correr el mismo ALTER antes del deploy.

## 3. Drift dev 2026-09-18 — migración completa aplicada a crm_dev

Restauración de la BD dev desde dump anterior a varios ALTERs + cambios de tipo
que `create_all` no puede aplicar. Diff completo modelos-vs-BD → migración en
`crm_backend/spec/migrations/2026-09-18_Schema_drift_planning_backend.02_16_18.sql`
(idempotente, `psql -v ON_ERROR_STOP=1 -f`; backup previo en
`db_crm_dev:/tmp/crm_dev_backup_20260918.sql`).

Aplicados:

1. `budgets.include_carryover` (§1, era el 500 de `GET /budget/planning`).
2. `linetypeenum` += 'PURCHASE' (§2).
3. `budget_lines.behavior_type` varchar→`behaviortypeenum` (los datos ya
   guardaban los NAMES mayúsculos; el default varchar `'fixed'` minúsculo era
   incompatible con la lectura del Enum → se reemplazó por `'FIXED'::behaviortypeenum`
   y SET NOT NULL). **NUEVO patrón de drift**: cambiar el tipo de una columna
   existente tampoco lo hace `create_all`.
4. Índices faltantes: `ix_actual_costs_document_number`,
   `ix_activity_types_category` (NO único: ver hallazgo abajo).
5. `customers.address` → DROP NOT NULL (nullable en modelo; dato legacy del dump).

Verificado: diff modelos-vs-BD sin gaps, `get_planning_scenarios` OK (6 filas
con `include_carryover`), toggle carryover roundtrip OK, filtros ORM de
`PURCHASE` y `behavior_type` OK.

**Hallazgos no aplicados (requieren decisión):**
- `activity_types.category`: el modelo declara `unique=True` pero la semilla
  tiene duplicados (Comercial x6, Mercadeo x3, General x2) ⇒ el índice único NO
  se puede crear; en una BD limpia `create_all` SÍ lo crearía y la carga de
  semilla fallaría. O quitar `unique` del modelo o limpiar datos.
- `actual_expenses.amount`: modelo `NUMERIC(15,2)` vs BD `float8` (funcional,
  sin error; convertiría con `USING round(amount::numeric,2)` si se desea).
- Producción: correr la migración completa (§1+§2 ya documentados como pendientes).

## 4. `budget_lines` += 3 columnas del motor de nómina (BE-S11-COLLABORATORS, backend.02_21 §4.8)

```sql
ALTER TABLE budget_lines
  ADD COLUMN IF NOT EXISTS id_collaborator    integer,
  ADD COLUMN IF NOT EXISTS cost_component_code varchar(20),
  ADD COLUMN IF NOT EXISTS source_engine       varchar(40);
```

- Mismo patrón que §1 (`include_carryover`) y que `has_iva` de BE-S10: las 6
  tablas nuevas del módulo (`collaborators`, `collaborator_salary_plans`,
  `labor_cost_parameters`, `labor_arl_rates`, `cost_components`,
  `collaborator_provision_accruals`) las crea `create_all` en la fase 1 del
  despliegue, pero `create_all` **nunca** agrega columnas a `budget_lines`
  (tabla existente). Sin este ALTER, desplegar el modelo nuevo rompe cualquier
  `GET/POST` sobre `budget_lines` con `UndefinedColumn` y el motor (R-13) no
  puede poblar el vínculo `source_engine`/`id_collaborator`/`cost_component_code`.
- Las tres son **nullable sin default** (D-S11-5): NULL en el 100 % de las filas
  existentes ⇒ retrocompatible (NFR-05). `id_collaborator` lleva NO lleva FK de
  BD a propósito (§4.7: la integridad la garantiza el motor y así el orden de
  creación de tablas es irrelevante).
- Sentencia completa (incluye el índice parcial opcional de rendimiento para
  R-13 y las verificaciones):
  `crm_backend/spec/migrations/2026-09-23_Schema_drift_collaborators_backend.02_21.sql`
  (idempotente; aplicar con
  `docker exec -i db_crm_dev psql -U postgres -d crm -v ON_ERROR_STOP=1 -f ...`).
- **Pendiente en DEV (fase 2 + fase 3):** correr el ALTER de arriba y luego el
  seed idempotente `python -m app.utils.seeds.laborCostSeed` (catálogo de 15
  componentes + vigencia 2026 de parámetros/ARL). ⚠ Los valores sembrados son
  los FICTICIOS del §4.3/§4.4 de la spec: **NUNCA sembrar producción sin la
  validación de contabilidad (DEP-01, bloqueante go-live)**.
- **PENDIENTE EN PRODUCCIÓN:** ALTER (misma sentencia) + seed con valores
  validados por contabilidad, ambos ANTES del deploy. Cero cambios de esquema
  en el lado real (SIIGO/ETLs intactos, D-S11-6/BR-13).

## 5. `budgets` += 4 columnas de saldo inicial configurable (BE-S7-INITBAL, backend.02_25 §3.2)

```sql
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_cash_mode VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_cash_manual NUMERIC(15,2) NOT NULL DEFAULT 0;
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_warehouse_mode VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS initial_warehouse_manual NUMERIC(15,2) NOT NULL DEFAULT 0;
```

- Config por escenario de los DOS saldos iniciales del flujo de planificación
  (efectivo y bodega), con modo independiente `carryover | manual` (BR-IB-01).
- `NUMERIC(15,2)` = mismo tipo real de `budget_lines.projected_amount`
  (orientativo `NUMERIC(18,2)` de la spec corregido al tipo del repo).
- El valor manual se persiste SIEMPRE, incluso en modo `carryover` (es la
  base de degradación sin fuente, BR-IB-04). El backend NUNCA deriva el valor
  por arrastre (SA-1/D-S7-9: esa fórmula vive en el FE `cashFlowPivot`).
- Defaults `manual`/`0` ⇒ filas existentes se comportan exactamente igual que
  hoy (BR-IB-06). Con estos ALTER las filas previas a la feature arruncan
  `manual`/`0` automáticamente (AC-S7-BE-9).
- **PENDIENTE EN DEV/PRODUCCIÓN:** correr los 4 ALTER ANTES del deploy
  (patrón R-S7-3: `create_all` nunca agrega columnas a `budgets`; sin ellos
  todo GET sobre budgets falla con `UndefinedColumn`).

## 6. `collaborators` += `pays_pension` (backend.02_27 §3, flag "Cotiza pension")

```sql
ALTER TABLE collaborators ADD COLUMN pays_pension BOOLEAN NOT NULL DEFAULT TRUE;
```

- Mismo patrón que §1 (`include_carryover`) y §4 (`budget_lines`): las 6 tablas
  del módulo de nómina las creó `create_all` en su día, pero `create_all`
  **nunca** agrega columnas a una tabla existente — sin este ALTER, cualquier
  `GET/POST` de colaboradores y el motor (R-13) fallan con `UndefinedColumn`.
- `NOT NULL DEFAULT TRUE` ⇒ colaboradores existentes arruncan `True`
  (comportamiento actual preservado: el motor emite `C_PENSION` solo si
  `pays_pension` es True, backend.02_27 §6.1).
- Fuente del flag: formulario/API (`pays_pension`) y plantilla de nómina
  (columna opcional **"Cotiza pension"**; vacía ⇒ alta `True` / re-import no
  toca el master, §7.1/§7.2).
- **PENDIENTE EN DEV/PRODUCCIÓN:** correr el ALTER ANTES del deploy del
  backend que incluye backend.02_27.
