-- 2026-10-15_tax_calendar_payment_year_align.sql
-- Aligns tax_calendar_periods.payment_year with the year of payment_due_date.
-- Older catalog rows were stored with the caused year instead of the payment
-- year (e.g. SIMPLE Bimestre 6 of 2026 declared 2027-01-21; ordinary ANUAL of
-- 2026 paid 2027-05-21). GET /budget/tax/calendar must stay readable — the
-- engine already derives payment_year from the date when it exists — but the
-- stored value should describe when the money actually leaves.
-- Rerunnable; run a backup first.

BEGIN;

UPDATE tax_calendar_periods
SET payment_year = EXTRACT(year FROM payment_due_date)::int
WHERE payment_year != EXTRACT(year FROM payment_due_date)::int;

COMMIT;
