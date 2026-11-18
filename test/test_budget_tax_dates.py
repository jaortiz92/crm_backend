"""Date-dimension regression tests for budget tax integration.

These tests intentionally use 2026/2027 because ordinary income tax for a
2026 budget is paid in 2027, while its P&L recognition remains December 2026.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.budgetTaxEngine import (
    aggregate_tax_cash_flow,
    tax_pnl_date,
    tax_result_locations,
)


def _row(tax_type, period_end, declaration=None, payment=None, trace=None):
    return SimpleNamespace(
        id_budget_tax_result=1,
        tax_type=tax_type,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        declaration_date=declaration,
        payment_date=payment,
        payment_year=payment.year if payment else None,
        calculation_trace=trace or {},
        tax_caused=Decimal("100"),
        advance_amount=Decimal("0"),
        withholding_amount=Decimal("0"),
        balance_payable=Decimal("100"),
    )


def test_ordinary_2026_is_pnl_december_but_paid_in_2027():
    row = _row(
        "income_ordinary",
        date(2026, 12, 31),
        declaration=date(2027, 4, 15),
        payment=date(2027, 4, 30),
        trace={"pnl_year": 2026, "pnl_month": 12},
    )

    assert tax_pnl_date(row, 2026) == date(2026, 12, 1)
    assert tax_result_locations(row, 2026) == {
        "pnl_month": 12,
        "pnl_year": 2026,
        "payment_date": date(2027, 4, 30),
        "payment_year": 2027,
    }


def test_ica_uses_declaration_month_and_falls_back_to_period_end():
    declared = _row(
        "ica", date(2026, 12, 31),
        declaration=date(2027, 2, 10), payment=date(2027, 2, 28),
    )
    fallback = _row(
        "ica", date(2026, 11, 30),
        declaration=None, payment=date(2027, 1, 31),
    )

    assert tax_pnl_date(declared, 2026) == date(2027, 2, 1)
    assert tax_pnl_date(fallback, 2026) == date(2026, 11, 1)


def test_cash_flow_keeps_2027_payment_for_2026_snapshot_and_credits_are_not_expense():
    ordinary = _row(
        "income_ordinary", date(2026, 12, 31), payment=date(2027, 4, 30),
        trace={"pnl_year": 2026, "pnl_month": 12},
    )
    reteiva = _row(
        "reteiva", date(2026, 12, 31), payment=date(2027, 1, 20),
    )
    reteiva.withholding_amount = Decimal("100")
    reteiva.balance_payable = Decimal("0")

    result = aggregate_tax_cash_flow([ordinary, reteiva])

    assert [row["payment_year"] for row in result["monthly"]] == [2027, 2027]
    assert result["totals"]["net_outflow"] == Decimal("100.00")
    # withholding is retained as a credit/saldo and is not a second payment.
    assert result["totals"]["withholding_amount"] == Decimal("100.00")
