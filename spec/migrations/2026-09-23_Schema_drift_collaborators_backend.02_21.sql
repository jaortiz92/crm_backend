-- ============================================================================
-- 2026-09-23_Schema_drift_collaborators_backend.02_21.sql
-- BE-S11-COLLABORATORS (spec backend.02_21 S4.8 fase 2): las 6 tablas nuevas
-- las crea Base.metadata.create_all al desplegar el codigo (fase 1); create_all
-- NUNCA agrega columnas a tablas EXISTENTES, por lo que las 3 columnas
-- nullable de budget_lines (D-S11-5) requieren este ALTER manual ANTES de
-- desplegar el codigo que las consume (precedente exacto:
-- budgets.include_carryover de BE-S6, note.md S1; y budget_lines.has_iva de
-- BE-S10). Sin el ALTER: todo SELECT/INSERT sobre budget_lines con el modelo
-- nuevo falla con UndefinedColumn, e import/recalculate del motor no pueden
-- poblar id_collaborator/cost_component_code/source_engine.
-- Aplicar con (autocommit por sentencia; dev):
--   docker exec db_crm_dev psql -U postgres -d crm -v ON_ERROR_STOP=1 \
--     -f 2026-09-23_Schema_drift_collaborators_backend.02_21.sql
-- ============================================================================

-- [1] S4.7 (D-S11-5): vinculacion motor<->linea. Las tres NULLABLES: NULL en
--     todas las filas existentes => 100% retrocompatible (NFR-05). Sin FK de
--     BD en id_collaborator (S4.7: integridad la garantiza el motor; asi el
--     orden de creacion de tablas no importa).
ALTER TABLE budget_lines
  ADD COLUMN IF NOT EXISTS id_collaborator    integer,
  ADD COLUMN IF NOT EXISTS cost_component_code varchar(20),
  ADD COLUMN IF NOT EXISTS source_engine       varchar(40);

-- [2] (Opcional, rendimiento R-13) indice parcial para el filtro de
--     reemplazo idempotente del motor (solo filas del motor).
CREATE INDEX IF NOT EXISTS ix_budget_lines_collaborator_engine
  ON budget_lines (id_collaborator, budget_date)
  WHERE source_engine LIKE 'collaborator_%';

-- ============================================================================
-- VERIFICACION post-aplicado:
--   SELECT column_name, data_type, is_nullable FROM information_schema.columns
--     WHERE table_name='budget_lines'
--     AND column_name IN ('id_collaborator','cost_component_code','source_engine');
--     => 3 filas, is_nullable = YES
--   SELECT count(*) FROM budget_lines WHERE source_engine IS NOT NULL;
--     => 0 (ningun motor corrio aun; toda fila legacy conserva NULL)
-- FASE 3 (seeds idempotentes, JAMAS con valores ficticios en prod - DEP-01):
--   python -m app.utils.seeds.laborCostSeed
-- ============================================================================

-- ENMIENDA 2026-09-28 (seed BE-S11 fallo StringDataRightTruncation): los
-- codigos extralegales sembrados PRE_EXTRALEGAL (14) y VAC_COMPENSATORIO (17)
-- excedian varchar(12) de [1]. Ancho definitivo: varchar(20) en code (PK),
-- component_code (FK del ledger) y budget_lines.cost_component_code. Idempotente
-- para entornos que ya aplicaron la version varchar(12):
ALTER TABLE cost_components
  ALTER COLUMN code TYPE varchar(20);
ALTER TABLE collaborator_provision_accruals
  ALTER COLUMN component_code TYPE varchar(20);
ALTER TABLE budget_lines
  ALTER COLUMN cost_component_code TYPE varchar(20);
ALTER TABLE collaborators
  ALTER COLUMN risk_class TYPE varchar(3);
ALTER TABLE labor_arl_rates
  ALTER COLUMN risk_class TYPE varchar(3);
