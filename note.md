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