-- ============================================================================
-- 2026-09-18_Schema_drift_planning_backend.02_16_18.sql
-- Alineacion DDL manual de la BD DEV con los ultimos specs de backend
-- (el proyecto usa Base.metadata.create_all: NUNCA altera tablas/enum existentes).
-- Fuente: crm_backend/note.md 1 y 2, specs backend.02_16 S3.2 y backend.02_18 S3.3,
-- y diff completo modelos-vs-BD (cero tablas faltantes; 1 columna, 2 enums, 2 indices).
-- Aplicar con: psql -v ON_ERROR_STOP=1 -f (autocommit por sentencia; PG16
-- exige que ALTER TYPE ADD VALUE no comparta transaccion con su uso).
-- ============================================================================

-- [1] BE-S6-CARRYOVER (backend.02_16 S3.2) ? fix del 500 en GET /budget/planning
--     (UndefinedColumn: budgets.include_carryover).
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS include_carryover BOOLEAN NOT NULL DEFAULT FALSE;

-- [2] BE-S8-BUDGET-PURCHASES (backend.02_18 S3.3) ? nota.md decia 'APLICADO EN DEV
--     2026-09-15' pero la BD actual (restaurada desde dump) NO lo tiene.
--     Sin esto, crear lineas de compra falla con invalid input value for enum.
ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';

-- [3] budget_lines.behavior_type: el modelo paso de String a Enum(BehaviorTypeEnum)
--     (create_all la deja como varchar heredada del dump). Los 91 datos existentes
--     ya guardan los NAMES en mayusculas (FIXED/VARIABLE_SALES/VARIABLE_RECEIVABLES),
--     que son exactamente las etiquetas de behaviortypeenum. Se convierte al enum
--     nativo y se elimina el default varchar 'fixed' minusculado (leer 'fixed' con
--     el modelo Enum nuevo provocaria LookupError en filas futuras por default).
ALTER TABLE budget_lines ALTER COLUMN behavior_type DROP DEFAULT;
ALTER TABLE budget_lines
  ALTER COLUMN behavior_type TYPE behaviortypeenum
    USING behavior_type::behaviortypeenum,
  ALTER COLUMN behavior_type SET DEFAULT 'FIXED'::behaviortypeenum,
  ALTER COLUMN behavior_type SET NOT NULL;

-- [4] Indices declarados index=True en modelos, ausentes en la BD (create_all no
--     los agrega a tablas existentes).
--     NOTA: activity_types.category esta ALSO unique=True en el modelo, pero los
--     datos semilla tienen duplicados (Comercial x6, Mercadeo x3, General x2), por
--     lo que UNICAMENTE se crea el indice NO-unico; la unicidad queda como
--     hallazgo para decidir (modelo vs datos).
CREATE INDEX IF NOT EXISTS ix_actual_costs_document_number ON actual_costs (document_number);
CREATE INDEX IF NOT EXISTS ix_activity_types_category ON activity_types (category);

-- [5] customers.address: NOT NULL legacy del dump vs nullable=True en el modelo
--     (0 filas con address NULL; relajar no pierde datos y evita 500 al crear
--     clientes sin direccion).
ALTER TABLE customers ALTER COLUMN address DROP NOT NULL;

-- ============================================================================
-- VERIFICACION post-aplicado:
--   SELECT unnest(enum_range(NULL::linetypeenum));
--     => INCOME | EXPENSE | PURCHASE
--   SELECT column_name, is_nullable, data_type FROM information_schema.columns
--     WHERE table_name='budgets' AND column_name='include_carryover';
--   SELECT atttypid::regtype FROM pg_attribute
--     WHERE attrelid='budget_lines'::regclass AND attname='behavior_type';
-- ============================================================================
