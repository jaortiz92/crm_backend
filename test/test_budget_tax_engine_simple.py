"""Focused unit tests for period-based SIMPLE tax calculation."""

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.models.budget import Budget, BudgetLine
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
    def __init__(self, budget, lines):
        self.budget = budget
        self.lines = lines

    def query(self, model):
        return _Query(self.budget if model is Budget else self.lines)

    def commit(self):
        pass


def _calendar(sequence, start_month, declaration_month):
    return SimpleNamespace(
        tax_type="simple",
        period_code="bimonthly",
        sequence=sequence,
        period_start=date(2027, start_month, 1),
        period_end=date(2027, start_month + 1, 28),
        declaration_due_date=date(2027, declaration_month, 20),
        payment_due_date=date(2027, declaration_month, 20),
        payment_year=2027,
        is_active=True,
    )


class SimpleTaxEngineTests(unittest.TestCase):
    def setUp(self):
        self.budget = SimpleNamespace(budget_year=2027)
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
            monthly_sales_taxable_base=None,
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

    def test_each_bimester_uses_its_own_income_bracket(self):
        lines = [
            SimpleNamespace(line_type="income", projected_amount=Decimal("100"),
                            budget_date=date(2027, 1, 15)),
            SimpleNamespace(line_type="income", projected_amount=Decimal("1000"),
                            budget_date=date(2027, 3, 15)),
        ]
        calendars = [_calendar(1, 1, 3), _calendar(2, 3, 5)]
        rates = [
            SimpleNamespace(tax_type="simple", is_active=True, regime="simple",
                            economic_activity_code="A", municipality_code=None,
                            income_min=Decimal("0"), income_max=Decimal("999"),
                            rate=Decimal("0.01"), fixed_amount=None,
                            valid_from=None, valid_to=None),
            SimpleNamespace(tax_type="simple", is_active=True, regime="simple",
                            economic_activity_code="A", municipality_code=None,
                            income_min=Decimal("1000"), income_max=None,
                            rate=Decimal("0.02"), fixed_amount=None,
                            valid_from=None, valid_to=None),
        ]
        db = _Session(self.budget, lines)
        saved = []
        with patch("app.services.budgetTaxEngine.list_tax_rates", return_value=rates), \
                patch("app.services.budgetTaxEngine.list_tax_calendar", return_value=calendars), \
                patch("app.services.budgetTaxEngine.clear_budget_tax_results"), \
                patch("app.services.budgetTaxEngine.add_budget_tax_result",
                      side_effect=lambda _db, **row: saved.append(row)), \
                patch("app.services.budgetTaxEngine.BudgetIvaEngine.events",
                      return_value=[]):
            result = BudgetTaxEngine(db).calculate(1, self.assumption, self.profile)

        simple = [row for row in result["results"] if row["tax_type"] == "simple"]
        self.assertEqual([row["taxable_base"] for row in simple],
                         [Decimal("100.00"), Decimal("1000.00")])
        self.assertEqual([row["tax_rate"] for row in simple],
                         [Decimal("0.01"), Decimal("0.02")])
        self.assertEqual([row["tax_caused"] for row in simple],
                         [Decimal("1.00"), Decimal("20.00")])
        self.assertEqual([row["advance_amount"] for row in simple],
                         [Decimal("0.00"), Decimal("0.00")])
        self.assertEqual([row["balance_payable"] for row in simple],
                         [Decimal("1.00"), Decimal("20.00")])
        self.assertEqual([row["payment_date"] for row in simple],
                         [date(2027, 3, 20), date(2027, 5, 20)])
        self.assertEqual(len([row for row in saved if row["tax_type"] == "simple"]), 2)

    def test_monthly_override_is_grouped_by_bimester(self):
        self.assumption.monthly_sales_taxable_base = {
            "2027-01": Decimal("300"), "2027-02": Decimal("200"),
            "2027-03": Decimal("50"), "2027-04": Decimal("25"),
        }
        calendars = [_calendar(1, 1, 3), _calendar(2, 3, 5)]
        rate = SimpleNamespace(
            tax_type="simple", is_active=True, regime="simple",
            economic_activity_code=None, municipality_code=None,
            income_min=None, income_max=None, rate=Decimal("0.01"),
            fixed_amount=None, valid_from=None, valid_to=None,
        )
        db = _Session(self.budget, [])
        with patch("app.services.budgetTaxEngine.list_tax_rates", return_value=[rate]), \
                patch("app.services.budgetTaxEngine.list_tax_calendar", return_value=calendars), \
                patch("app.services.budgetTaxEngine.clear_budget_tax_results"), \
                patch("app.services.budgetTaxEngine.add_budget_tax_result"), \
                patch("app.services.budgetTaxEngine.BudgetIvaEngine.events",
                      return_value=None):
            result = BudgetTaxEngine(db).calculate(1, self.assumption, self.profile)

        simple = [row for row in result["results"] if row["tax_type"] == "simple"]
        self.assertEqual([row["taxable_base"] for row in simple],
                         [Decimal("500.00"), Decimal("75.00")])


if __name__ == "__main__":
    unittest.main()
