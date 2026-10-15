-- 2026-10-14_tax_profile_active_unique.sql
-- Manual migration for app/models/budget/taxPlanning.py (TaxProfile).
-- Replaces the UNIQUE(id_company, tax_year, regime, status) constraint, which
-- blocked a second draft or archived profile for the same company/year/regime,
-- with a partial unique index that only restricts ACTIVE profiles.
-- Base.metadata.create_all does NOT alter existing tables: run this file.
-- Make a backup first. Rerunnable.

BEGIN;

-- Fails (and rolls back) if more than one active profile already exists for
-- the same company/year/regime. Resolve those rows manually before rerunning.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tax_profiles
        WHERE status = 'active'
        GROUP BY id_company, tax_year, regime
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate active tax profiles exist; resolve them before this migration';
    END IF;
END $$;

ALTER TABLE tax_profiles DROP CONSTRAINT IF EXISTS uq_tax_profile_company_year_regime_status;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tax_profile_active_company_year_regime
    ON tax_profiles (id_company, tax_year, regime)
    WHERE status = 'active';

COMMIT;
