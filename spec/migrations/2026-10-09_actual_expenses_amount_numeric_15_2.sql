-- 2026-10-09_actual_expenses_amount_numeric_15_2.sql
-- Alinea actual_expenses.amount (actualmente double precision) con el modelo
-- SQLAlchemy NUMERIC(15,2). No ejecutar automáticamente: aplicar manualmente
-- en una ventana de mantenimiento y revisar primero la comprobación previa.
--
-- IMPORTANTE: el cast a NUMERIC(15,2) redondea los valores existentes a dos
-- decimales. Si algún valor no cabe en NUMERIC(15,2), la comprobación previa
-- aborta antes del ALTER. Todo se ejecuta en una transacción.

BEGIN;

-- Comprobación previa y guardas: exige tabla/columna y solo convierte desde
-- double precision (o permite repetir la migración si ya está en NUMERIC(15,2)).
-- El rango de NUMERIC(15,2) es -9999999999999.99 a 9999999999999.99.
DO $$
DECLARE
    column_type text;
    column_precision integer;
    column_scale integer;
BEGIN
    SELECT data_type, numeric_precision, numeric_scale
      INTO column_type, column_precision, column_scale
      FROM information_schema.columns
     WHERE table_schema = current_schema()
       AND table_name = 'actual_expenses'
       AND column_name = 'amount';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No se encontró %.actual_expenses.amount', current_schema();
    END IF;

    IF column_type NOT IN ('double precision', 'numeric') THEN
        RAISE EXCEPTION 'Tipo inesperado para actual_expenses.amount: %', column_type;
    END IF;

    IF column_type = 'numeric'
       AND (column_precision = 15 AND column_scale = 2) THEN
        RAISE NOTICE 'actual_expenses.amount ya es NUMERIC(15,2); no requiere conversión';
    ELSE
        IF EXISTS (
            SELECT 1
              FROM actual_expenses
             WHERE amount IS NOT NULL
               AND (
                   amount::text IN ('NaN', 'Infinity', '-Infinity')
                   OR amount::numeric < -9999999999999.99
                   OR amount::numeric > 9999999999999.99
               )
        ) THEN
            RAISE EXCEPTION
                'Hay valores de actual_expenses.amount que no caben en NUMERIC(15,2); no se aplicó el ALTER';
        END IF;
    END IF;
END;
$$;

-- Repetible: omite el ALTER cuando el tipo/precisión/escala ya son los deseados.
DO $$
DECLARE
    column_type text;
    column_precision integer;
    column_scale integer;
BEGIN
    SELECT data_type, numeric_precision, numeric_scale
      INTO column_type, column_precision, column_scale
      FROM information_schema.columns
     WHERE table_schema = current_schema()
        AND table_name = 'actual_expenses'
        AND column_name = 'amount';

    -- El default legacy '0'::double precision puede impedir el cambio de tipo.
    -- Se normaliza tanto al convertir como al repetir sobre NUMERIC(15,2).
    EXECUTE format(
        'ALTER TABLE %I.actual_expenses ALTER COLUMN amount DROP DEFAULT',
        current_schema()
    );

    IF NOT (column_type = 'numeric'
            AND column_precision = 15
            AND column_scale = 2) THEN
        EXECUTE format(
            'ALTER TABLE %I.actual_expenses ALTER COLUMN amount TYPE NUMERIC(15,2) USING amount::NUMERIC(15,2)',
            current_schema()
        );
    END IF;

    EXECUTE format(
        'ALTER TABLE %I.actual_expenses ALTER COLUMN amount SET DEFAULT 0::numeric',
        current_schema()
    );
END;
$$;

-- Comprobación posterior: falla la transacción si el esquema no quedó alineado.
DO $$
DECLARE
    column_type text;
    column_precision integer;
    column_scale integer;
    column_default text;
BEGIN
    SELECT c.data_type, c.numeric_precision, c.numeric_scale, c.column_default
      INTO column_type, column_precision, column_scale, column_default
      FROM information_schema.columns AS c
     WHERE c.table_schema = current_schema()
       AND c.table_name = 'actual_expenses'
       AND c.column_name = 'amount';

    IF NOT FOUND
       OR column_type <> 'numeric'
       OR column_precision <> 15
       OR column_scale <> 2 THEN
        RAISE EXCEPTION
            'Verificación posterior fallida: actual_expenses.amount debería ser NUMERIC(15,2)';
    END IF;

    IF position('double precision' IN lower(coalesce(column_default, ''))) > 0 THEN
        RAISE EXCEPTION
            'Verificación posterior fallida: actual_expenses.amount no debe conservar un DEFAULT double precision (column_default=%)',
            column_default;
    END IF;
END;
$$;

-- Comprobación consultiva posterior al aplicar:
-- SELECT data_type, numeric_precision, numeric_scale
--   FROM information_schema.columns
--  WHERE table_schema = current_schema()
--    AND table_name = 'actual_expenses' AND column_name = 'amount';
-- Resultado esperado: numeric | 15 | 2.

COMMIT;
