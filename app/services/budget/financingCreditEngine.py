"""Pure Decimal amortization engine for monthly-periodic financing schedules.

This engine is deliberately explicit about rate conventions. It does not
provide day-count accrual: only monthly-periodic installments are supported.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import List, Optional


CENT = Decimal("0.01")
ZERO = Decimal("0")
SUPPORTED_METHODS = {"french_fixed_payment", "german_fixed_principal"}
SUPPORTED_RATE_CONVENTIONS = {"nominal_annual", "effective_annual"}


class FinancingScheduleError(ValueError):
    """User-provided credit conditions cannot produce a valid schedule."""


@dataclass(frozen=True)
class InstallmentProjection:
    installment_number: int
    period_start: date
    period_end: date
    principal_amount: Decimal
    interest_amount: Decimal
    insurance_amount: Decimal
    opening_balance: Decimal
    closing_balance: Decimal
    rate_used: Decimal
    rate_convention: str
    day_count_convention: str
    method: str

    @property
    def total_amount(self) -> Decimal:
        return self.principal_amount + self.interest_amount + self.insurance_amount


def decimal_value(value, field: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise FinancingScheduleError(f"{field} must be a decimal amount") from exc
    if not result.is_finite():
        raise FinancingScheduleError(f"{field} must be finite")
    return result


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_rate(annual_rate: Decimal, rate_convention: str,
                 day_count_convention: str) -> Decimal:
    if rate_convention not in SUPPORTED_RATE_CONVENTIONS:
        raise FinancingScheduleError("rate_convention must be nominal_annual or effective_annual")
    if day_count_convention != "monthly_periodic":
        raise FinancingScheduleError("Only day_count_convention='monthly_periodic' is supported")
    if annual_rate < ZERO:
        raise FinancingScheduleError("annual_rate cannot be negative")
    if rate_convention == "nominal_annual":
        return annual_rate / Decimal(12)
    with localcontext() as context:
        context.prec = 40
        return ((Decimal(1) + annual_rate) ** (Decimal(1) / Decimal(12))) - Decimal(1)


def add_months(preferred: date, month_offset: int) -> date:
    absolute_month = preferred.year * 12 + preferred.month - 1 + month_offset
    year, month0 = divmod(absolute_month, 12)
    month = month0 + 1
    day = min(preferred.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def generate_schedule(*, opening_balance, annual_rate, rate_convention: str,
                      day_count_convention: str, method: str,
                      term_installments: int, first_due_date: date,
                      schedule_start_date: date,
                      insurance_per_installment=ZERO,
                      date_anchor: Optional[date] = None,
                      first_due_month_offset: int = 0) -> List[InstallmentProjection]:
    """Return monthly installments; all monetary outputs are COP Decimals."""
    if method not in SUPPORTED_METHODS:
        raise FinancingScheduleError("method must be french_fixed_payment or german_fixed_principal")
    if not isinstance(term_installments, int) or term_installments <= 0:
        raise FinancingScheduleError("term_installments must be greater than zero")
    principal = _quantize(decimal_value(opening_balance, "opening_balance"))
    annual = decimal_value(annual_rate, "annual_rate")
    insurance = _quantize(decimal_value(insurance_per_installment, "insurance_per_installment"))
    if principal <= ZERO:
        raise FinancingScheduleError("opening_balance must be greater than zero")
    if insurance < ZERO:
        raise FinancingScheduleError("insurance_per_installment cannot be negative")
    if first_due_date <= schedule_start_date:
        raise FinancingScheduleError("first_due_date must be after the financing start date")
    date_anchor = date_anchor or first_due_date
    if not isinstance(first_due_month_offset, int) or first_due_month_offset < 0:
        raise FinancingScheduleError("first_due_month_offset must be a non-negative integer")
    if add_months(date_anchor, first_due_month_offset) != first_due_date:
        raise FinancingScheduleError("first_due_date does not match the monthly date anchor")
    periodic_rate = monthly_rate(annual, rate_convention, day_count_convention)

    with localcontext() as context:
        context.prec = 40
        if method == "french_fixed_payment":
            if periodic_rate == ZERO:
                fixed_payment = principal / Decimal(term_installments)
            else:
                fixed_payment = principal * periodic_rate / (
                    Decimal(1) - (Decimal(1) + periodic_rate) ** Decimal(-term_installments)
                )
        else:
            fixed_principal = principal / Decimal(term_installments)

        rows: List[InstallmentProjection] = []
        balance = principal
        previous_end = schedule_start_date
        for number in range(1, term_installments + 1):
            due_date = add_months(
                date_anchor, first_due_month_offset + number - 1
            )
            interest = _quantize(balance * periodic_rate)
            if number == term_installments:
                capital = balance
            elif method == "french_fixed_payment":
                capital = _quantize(fixed_payment - interest)
            else:
                capital = _quantize(fixed_principal)
            if capital <= ZERO or capital > balance:
                raise FinancingScheduleError(
                    "Conditions do not produce a valid amortizing installment"
                )
            closing = _quantize(balance - capital)
            rows.append(InstallmentProjection(
                installment_number=number,
                period_start=previous_end,
                period_end=due_date,
                principal_amount=capital,
                interest_amount=interest,
                insurance_amount=insurance,
                opening_balance=_quantize(balance),
                closing_balance=closing,
                rate_used=annual,
                rate_convention=rate_convention,
                day_count_convention=day_count_convention,
                method=method,
            ))
            balance = closing
            previous_end = due_date

    if balance != ZERO:
        raise FinancingScheduleError("Schedule does not amortize the opening balance")
    if abs(sum((row.principal_amount for row in rows), ZERO) - principal) > CENT:
        raise FinancingScheduleError("Principal installments do not reconcile to opening balance")
    return rows
