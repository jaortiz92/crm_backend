"""Focused tests for the tax-to-cash-flow and P&L classification bridge."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.budgetTaxEngine import aggregate_tax_cash_flow


def _row(tax_type, caused, advance=0, withholding=0, payable=0, month=3):
    return SimpleNamespace(
        id_budget_tax_result=month,
        tax_type=tax_type,
        tax_caused=Decimal(str(caused)),
        advance_amount=Decimal(str(advance)),
        withholding_amount=Decimal(str(withholding)),
        balance_payable=Decimal(str(payable)),
        payment_date=date(2027, month, 20),
        payment_year=2027,
    )


def test_tax_cash_flow_aggregates_every_type_and_keeps_credits_separate():
    result = aggregate_tax_cash_flow([
        _row("simple", 100, advance=100),
        _row("reteiva", 20, withholding=15, payable=5),
        _row("ica", 30, payable=30, month=5),
    ])

    march = result["monthly"][0]
    assert march["tax_caused"] == Decimal("120.00")
    assert march["advance_amount"] == Decimal("100.00")
    assert march["withholding_amount"] == Decimal("15.00")
    assert march["payments"] == Decimal("5.00")
    # The retention is a credit, not a second cash payment.
    assert march["net_outflow"] == Decimal("105.00")
    assert {item["tax_type"] for item in march["by_type"]} == {"reteiva", "simple"}
    assert result["totals"]["tax_caused"] == Decimal("150.00")
    assert result["totals"]["net_outflow"] == Decimal("135.00")


def test_tax_cash_flow_warns_for_undated_snapshot():
    row = _row("withholding", 10)
    row.payment_date = None
    row.payment_year = None
    result = aggregate_tax_cash_flow([row])

    assert result["monthly"][0]["period"] == "undated"
    assert "has no payment date" in result["warnings"][0]
