-- 2026-10-09_financing_credit_schema_sync.sql
-- Sincronización MANUAL y aditiva con app/models/budget/financingCredit.py.
-- Haga y verifique un respaldo antes de ejecutar este archivo.
-- Ejecute esta migración antes de volver a usar el endpoint de creación de
-- créditos. Es rerunnable; Base.metadata.create_all NO sustituye esta migración
-- ni sincroniza las tablas existentes.
--
-- Todo el cambio se ejecuta en una transacción. Si el backfill o una
-- constraint no valida los datos existentes, la transacción debe abortar y
-- hacer rollback. No se asignan valores artificiales a las cuotas.

BEGIN;

-- Asegura la estructura mínima y añade primero las columnas de cuotas como
-- nullable para poder completar sus datos desde el crédito padre.
ALTER TABLE financing_credits
    ADD COLUMN IF NOT EXISTS closure_date DATE NULL,
    ADD COLUMN IF NOT EXISTS closure_balance NUMERIC(15,2) NULL;

ALTER TABLE financing_credit_installments
    ADD COLUMN IF NOT EXISTS rate_convention VARCHAR(24) NULL,
    ADD COLUMN IF NOT EXISTS day_count_convention VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS method VARCHAR(32) NULL,
    ADD COLUMN IF NOT EXISTS id_cost_center INTEGER NULL;

-- Las cuatro propiedades se heredan del crédito. Un registro huérfano o un
-- valor faltante en el padre no se resuelve inventando datos: la guarda que
-- sigue informa de la cantidad afectada y aborta la migración.
UPDATE financing_credit_installments AS installment
   SET rate_convention = COALESCE(installment.rate_convention, credit.rate_convention),
       day_count_convention = COALESCE(installment.day_count_convention, credit.day_count_convention),
       method = COALESCE(installment.method, credit.method),
       id_cost_center = COALESCE(installment.id_cost_center, credit.id_cost_center)
  FROM financing_credits AS credit
 WHERE credit.id_financing_credit = installment.id_financing_credit;

DO $$
DECLARE
    missing_rate_convention bigint;
    missing_day_count_convention bigint;
    missing_method bigint;
    missing_cost_center bigint;
BEGIN
    SELECT count(*) FILTER (WHERE rate_convention IS NULL),
           count(*) FILTER (WHERE day_count_convention IS NULL),
           count(*) FILTER (WHERE method IS NULL),
           count(*) FILTER (WHERE id_cost_center IS NULL)
      INTO missing_rate_convention,
           missing_day_count_convention,
           missing_method,
           missing_cost_center
      FROM financing_credit_installments;

    IF missing_rate_convention > 0
       OR missing_day_count_convention > 0
       OR missing_method > 0
       OR missing_cost_center > 0 THEN
        RAISE EXCEPTION
            'Backfill de financing_credit_installments incompleto: rate_convention NULL=%, day_count_convention NULL=%, method NULL=%, id_cost_center NULL=%. Revise cuotas huérfanas y valores del crédito padre; corrija los datos y vuelva a ejecutar.',
            missing_rate_convention,
            missing_day_count_convention,
            missing_method,
            missing_cost_center;
    END IF;
END;
$$;

ALTER TABLE financing_credit_installments
    ALTER COLUMN rate_convention SET NOT NULL,
    ALTER COLUMN day_count_convention SET NOT NULL,
    ALTER COLUMN method SET NOT NULL,
    ALTER COLUMN id_cost_center SET NOT NULL;

-- Añade únicamente constraints ausentes. PostgreSQL valida cada constraint
-- contra todas las filas existentes; cualquier infracción aborta la transacción.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_insurance_nonnegative'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_insurance_nonnegative
            CHECK (insurance_per_installment >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_original_principal'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_original_principal
            CHECK (original_principal IS NULL OR original_principal > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_status'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_status
            CHECK (status IN ('active', 'closed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_origin'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_origin
            CHECK (origin_type IN ('new', 'legacy'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_method'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_method
            CHECK (method IN ('french_fixed_payment', 'german_fixed_principal'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_currency'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_currency
            CHECK (currency = 'COP');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_frequency'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_frequency
            CHECK (frequency = 'monthly');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_closure_state'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_closure_state
            CHECK (
                (status = 'active' AND closure_date IS NULL AND closure_balance IS NULL)
                OR (status = 'closed' AND closure_date IS NOT NULL AND closure_balance = 0)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_rate_convention'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_rate_convention
            CHECK (rate_convention IN ('nominal_annual', 'effective_annual'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_day_count'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_day_count
            CHECK (day_count_convention = 'monthly_periodic');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credits'::regclass
           AND conname = 'ck_financing_credit_origin_dates'
    ) THEN
        ALTER TABLE financing_credits ADD CONSTRAINT ck_financing_credit_origin_dates
            CHECK (
                (origin_type = 'legacy' AND cutoff_date IS NOT NULL
                    AND disbursement_date IS NULL AND original_principal IS NULL
                    AND first_due_date > cutoff_date)
                OR (origin_type = 'new' AND disbursement_date IS NOT NULL
                    AND original_principal IS NOT NULL
                    AND opening_balance = original_principal
                    AND first_due_date > disbursement_date)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_rate_convention'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_rate_convention
            CHECK (rate_convention IN ('nominal_annual', 'effective_annual'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_day_count'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_day_count
            CHECK (day_count_convention = 'monthly_periodic');
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_method'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_method
            CHECK (method IN ('french_fixed_payment', 'german_fixed_principal'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_cost_center'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_cost_center
            CHECK (id_cost_center > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_projection_status'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_projection_status
            CHECK (projection_status IN ('projected', 'suspended'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_opening_positive'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_opening_positive
            CHECK (opening_balance > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'financing_credit_installments'::regclass
           AND conname = 'ck_financing_installment_rate_nonnegative'
    ) THEN
        ALTER TABLE financing_credit_installments ADD CONSTRAINT ck_financing_installment_rate_nonnegative
            CHECK (rate_used >= 0);
    END IF;
END;
$$;

-- Verificación posterior: exige las columnas con tipos/nullability esperados
-- y todas las constraints del modelo registradas y validadas.
DO $$
DECLARE
    expected_constraint record;
    missing_constraints text[] := ARRAY[]::text[];
    bad_columns text[] := ARRAY[]::text[];
    column_ok boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credits'
           AND column_name = 'closure_date'
           AND data_type = 'date'
           AND is_nullable = 'YES'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credits.closure_date DATE NULL'); END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credits'
           AND column_name = 'closure_balance'
           AND data_type = 'numeric'
           AND numeric_precision = 15
           AND numeric_scale = 2
           AND is_nullable = 'YES'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credits.closure_balance NUMERIC(15,2) NULL'); END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credit_installments'
           AND column_name = 'rate_convention'
           AND data_type = 'character varying'
           AND character_maximum_length = 24
           AND is_nullable = 'NO'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credit_installments.rate_convention VARCHAR(24) NOT NULL'); END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credit_installments'
           AND column_name = 'day_count_convention'
           AND data_type = 'character varying'
           AND character_maximum_length = 32
           AND is_nullable = 'NO'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credit_installments.day_count_convention VARCHAR(32) NOT NULL'); END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credit_installments'
           AND column_name = 'method'
           AND data_type = 'character varying'
           AND character_maximum_length = 32
           AND is_nullable = 'NO'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credit_installments.method VARCHAR(32) NOT NULL'); END IF;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'financing_credit_installments'
           AND column_name = 'id_cost_center'
           AND data_type = 'integer'
           AND is_nullable = 'NO'
    ) INTO column_ok;
    IF NOT column_ok THEN bad_columns := array_append(bad_columns, 'financing_credit_installments.id_cost_center INTEGER NOT NULL'); END IF;

    IF cardinality(bad_columns) > 0 THEN
        RAISE EXCEPTION 'Verificación de columnas fallida: %', array_to_string(bad_columns, ', ');
    END IF;

    FOR expected_constraint IN
        SELECT 'financing_credits'::regclass AS table_oid, constraint_name
          FROM (VALUES
              ('ck_financing_credit_opening_balance'),
              ('ck_financing_credit_annual_rate'),
              ('ck_financing_credit_term'),
              ('ck_financing_credit_insurance_nonnegative'),
              ('ck_financing_credit_original_principal'),
              ('ck_financing_credit_status'),
              ('ck_financing_credit_origin'),
              ('ck_financing_credit_method'),
              ('ck_financing_credit_currency'),
              ('ck_financing_credit_frequency'),
              ('ck_financing_credit_closure_state'),
              ('ck_financing_credit_rate_convention'),
              ('ck_financing_credit_day_count'),
              ('ck_financing_credit_origin_dates')
          ) AS credit_constraints(constraint_name)
        UNION ALL
        SELECT 'financing_credit_installments'::regclass AS table_oid, constraint_name
          FROM (VALUES
              ('uq_financing_installment_revision'),
              ('ck_financing_installment_number'),
              ('ck_financing_principal_nonnegative'),
              ('ck_financing_interest_nonnegative'),
              ('ck_financing_insurance_nonnegative'),
              ('ck_financing_installment_opening_positive'),
              ('ck_financing_closing_nonnegative'),
              ('ck_financing_installment_rate_nonnegative'),
              ('ck_financing_installment_cost_center'),
              ('ck_financing_installment_rate_convention'),
              ('ck_financing_installment_day_count'),
              ('ck_financing_installment_method'),
              ('ck_financing_installment_projection_status')
          ) AS installment_constraints(constraint_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = expected_constraint.table_oid
               AND conname = expected_constraint.constraint_name
               AND convalidated
        ) THEN
            missing_constraints := array_append(
                missing_constraints,
                expected_constraint.table_oid::regclass::text || '.' || expected_constraint.constraint_name
            );
        END IF;
    END LOOP;

    IF cardinality(missing_constraints) > 0 THEN
        RAISE EXCEPTION 'Verificación de constraints fallida (ausentes o no validadas): %',
            array_to_string(missing_constraints, ', ');
    END IF;
END;
$$;

COMMIT;
