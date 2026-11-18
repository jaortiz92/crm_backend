-- BE-S12-FINANCING-CREDITS: MANUAL PostgreSQL migration; do not run blindly.
-- Take a verified backup and inspect nulls/ranges/rounding deltas before
-- applying. This affects the shared budget_lines table and all budget users.
-- create_all does NOT add this column or convert the existing Float type.

ALTER TABLE budget_lines
    ADD COLUMN IF NOT EXISTS source_engine_id integer;

-- Safe to rerun: PostgreSQL numeric -> same numeric conversion preserves cents.
ALTER TABLE budget_lines
    ALTER COLUMN projected_amount TYPE numeric(15,2)
    USING round(projected_amount::numeric, 2);

CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_lines_financing_source
    ON budget_lines (id_budget, source_engine, source_engine_id, cost_component_code)
    WHERE source_engine = 'financing_credit';

-- Recommended preflight checks (run separately and review results):
-- SELECT count(*) FROM budget_lines WHERE projected_amount IS NULL;
-- SELECT min(projected_amount), max(projected_amount) FROM budget_lines;
-- SELECT sum(abs(projected_amount::numeric - round(projected_amount::numeric, 2)))
--   FROM budget_lines;
