"""SIMPLE credits: applied in period order, liquidation on the last period only."""

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.models.budget import Budget
from app.services.budgetTaxEngine import BudgetTaxEngine


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_args):
        return self

    def first(self):
        return self.value

    def all(self):
        return self.value


class _Session:
    def __init__(self, budget):
        self.budget = budget

    def query(self, model):
        return _Query(self.budget if model is Budget else [])

    def commit(self):
        pass


def _calendar(sequence):
    start_month = sequence * 2 - 1
    due_month = min(start_month + 2, 12)
    return SimpleNamespace(
        tax_type="simple",
        period_code=f"B{sequence}",
        sequence=sequence,
        period_start=date(2027, start_month, 1),
        period_end=date(2027, start_month + 1, 28),
        declaration_due_date=date(2027, due_month, 20),
        payment_due_date=date(2027, due_month, 20),
        payment_year=2027,
        is_active=True,
    )


class SimpleCreditsTests(unittest.TestCase):
    def setUp(self):
        self.budget = SimpleNamespace(id_budget=1, budget_year=2027)
        # 1% on 1000 per bimester: every bimester causes 10, the year 60.
        self.assumption = SimpleNamespace(
            id_budget_tax_assumption=10,
            taxable_income_override=None,
            non_deductible_expenses=Decimal("0"),
            exempt_income=Decimal("0"),
            taxable_income_adjustments=Decimal("0"),
            tax_losses=Decimal("0"),
            tax_discounts=Decimal("0"),
            prior_advances=Decimal("0"),
            prior_withholdings=Decimal("0"),
            monthly_sales_taxable_base={f"bimestre_{i}": 1000 for i in range(1, 7)},
            withholding_base=None,
            withholding_suffered=Decimal("0"),
            reteiva_suffered=Decimal("0"),
            reteica_base=None,
        )
        self.profile = SimpleNamespace(
            regime="simple",
            economic_activity_code="A",
            main_municipality_code=None,
            iva_responsible=False,
            reteiva_agent=False,
            withholding_agent=False,
            reteica_agent=False,
        )
        self.rates = [SimpleNamespace(
            tax_type="simple", is_active=True, regime="simple", economic_activity_code=None,
            municipality_code=None, income_min=None, income_max=None, rate=Decimal("0.01"),
            fixed_amount=None, valid_from=None, valid_to=None,
        )]
        self.calendars = [_calendar(i) for i in range(1, 7)]

    def _calculate(self):
        saved = []
        with patch("app.services.budgetTaxEngine.list_tax_rates", return_value=self.rates), \
                patch("app.services.budgetTaxEngine.list_tax_calendar", return_value=self.calendars), \
                patch("app.services.budgetTaxEngine.clear_budget_tax_results"), \
                patch("app.services.budgetTaxEngine.add_budget_tax_result",
                      side_effect=lambda _db, **row: saved.append(row)), \
                patch("app.services.budgetTaxEngine.BudgetIvaEngine.events", return_value=[]):
            result = BudgetTaxEngine(_Session(self.budget)).calculate(1, self.assumption, self.profile)
        return result, [row for row in result["results"] if row["tax_type"] == "simple"]

    def test_credit_is_consumed_in_period_order_until_exhausted(self):
        self.assumption.prior_advances = Decimal("25")
        _, simple = self._calculate()

        self.assertEqual([row["tax_caused"] for row in simple], [Decimal("10.00")] * 6)
        self.assertEqual([row["balance_payable"] for row in simple],
                         [Decimal("0.00"), Decimal("0.00"), Decimal("5.00"),
                          Decimal("10.00"), Decimal("10.00"), Decimal("10.00")])
        liquidation = simple[-1]["calculation_trace"]["liquidation"]
        self.assertEqual(liquidation["annual_caused"], "60.00")
        self.assertEqual(liquidation["credits_applied"], "25.00")
        self.assertEqual(liquidation["payments"], "35.00")
        self.assertEqual(liquidation["balance"], "0.00")
        self.assertEqual(liquidation["credits_lost"], "0.00")
        self.assertNotIn("liquidation", simple[0]["calculation_trace"])

    def test_credit_larger_than_annual_tax_is_lost(self):
        self.assumption.prior_advances = Decimal("100")
        self.assumption.prior_withholdings = Decimal("30")
        result, simple = self._calculate()

        self.assertEqual([row["balance_payable"] for row in simple], [Decimal("0.00")] * 6)
        self.assertEqual(simple[-1]["calculation_trace"]["liquidation"]["credits_lost"], "70.00")
        self.assertTrue(any("is lost" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
