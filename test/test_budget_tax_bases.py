"""Unit tests for the tax bases and the read-only projection contract.

Covers the audit fixes without touching the database:
- withholding in the source acts on expenses (payments to third parties),
  NOT on income;
- the ReteIVA base is the IVA of purchases (import + nationalization),
  not the IVA charged on sales, and no ReteIVA row is emitted when the
  profile is not an agent with no suffered ReteIVA;
- ``persist=False`` (regime comparison) never replaces the persisted
  snapshots and never commits;
- the regime comparison summary only aggregates the regime tax types.
"""

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
        self.commit_count = 0

    def query(self, model):
        return _Query(self.budget if model is Budget else self.lines)

    def commit(self):
        self.commit_count += 1


def _line(line_type, amount, month):
    return SimpleNamespace(
        line_type=line_type,
        projected_amount=Decimal(amount),
        budget_date=date(2027, month, 10),
    )


def _rate(tax_type, rate):
    return SimpleNamespace(
        tax_type=tax_type, is_active=True, regime=None,
        economic_activity_code=None, municipality_code=None,
        income_min=None, income_max=None,
        rate=Decimal(rate), fixed_amount=None,
        valid_from=None, valid_to=None,
    )


class BudgetTaxBasesTests(unittest.TestCase):
    def _budget(self):
        return SimpleNamespace(id_budget=1, budget_year=2027)

    def _assumption(self, **overrides):
        values = dict(
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
        values.update(overrides)
        return SimpleNamespace(**values)

    def _profile(self, **overrides):
        values = dict(
            regime="ordinary",
            economic_activity_code=None,
            main_municipality_code=None,
            iva_responsible=False,
            withholding_agent=False,
            reteiva_agent=False,
            reteica_agent=False,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def _calculate(self, lines, rates, assumption, profile, events=None,
                   persist=True, add_mock=None, clear_mock=None, calendars=None):
        db = _Session(self._budget(), lines)
        with patch("app.services.budgetTaxEngine.list_tax_rates", return_value=rates), \
                patch("app.services.budgetTaxEngine.list_tax_calendar",
                      return_value=calendars or []), \
                patch("app.services.budgetTaxEngine.clear_budget_tax_results",
                      side_effect=clear_mock), \
                patch("app.services.budgetTaxEngine.add_budget_tax_result",
                      side_effect=add_mock), \
                patch("app.services.budgetTaxEngine.BudgetIvaEngine.events",
                      return_value=events or []):
            result = BudgetTaxEngine(db).calculate(1, assumption, profile, persist=persist)
        return result, db

    # ── Punto 8: withholding sobre gastos ─────────────────────────────

    def test_withholding_defaults_to_expenses_not_income(self):
        lines = [_line("income", 1000000, 1),
                 _line("expense", 400000, 2),
                 _line("purchase", 100000, 3)]
        result, _ = self._calculate(
            lines, [_rate("withholding", "0.02")],
            self._assumption(), self._profile(withholding_agent=True),
        )
        rows = [r for r in result["results"] if r["tax_type"] == "withholding"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["taxable_base"], Decimal("500000.00"))
        self.assertEqual(rows[0]["tax_caused"], Decimal("10000.00"))
        self.assertEqual(rows[0]["calculation_trace"]["base_source"], "budget_expenses")

    def test_withholding_explicit_base_wins_and_is_traced(self):
        lines = [_line("income", 1000000, 1), _line("expense", 400000, 2)]
        result, _ = self._calculate(
            lines, [_rate("withholding", "0.02")],
            self._assumption(withholding_base=Decimal("200000")),
            self._profile(withholding_agent=True),
        )
        row = next(r for r in result["results"] if r["tax_type"] == "withholding")
        self.assertEqual(row["taxable_base"], Decimal("200000.00"))
        self.assertEqual(row["tax_caused"], Decimal("4000.00"))
        self.assertEqual(row["calculation_trace"]["base_source"], "assumption")

    def test_withholding_is_skipped_when_profile_is_not_agent(self):
        lines = [_line("expense", 400000, 2)]
        result, _ = self._calculate(
            lines, [_rate("withholding", "0.02")],
            self._assumption(), self._profile(withholding_agent=False),
        )
        self.assertNotIn("withholding", {r["tax_type"] for r in result["results"]})

    # ── Punto 11: reteIVA sobre compras ───────────────────────────────

    def _iva_events(self):
        return [
            {"date": "2027-01-10", "concept": "import_vat", "side": "deductible",
             "id_budget_line": 1, "amount": 190000.0},
            {"date": "2027-01-10", "concept": "nationalization_vat", "side": "deductible",
             "id_budget_line": 1, "amount": 95000.0},
            # Sales IVA (generated) and fixed-expense IVA are NOT the reteIVA base.
            {"date": "2027-01-15", "concept": "ventas", "side": "generated",
             "id_budget_line": 2, "amount": 1900.0},
            {"date": "2027-02-01", "concept": "fixed_expenses", "side": "deductible",
             "id_budget_line": 3, "amount": 19000.0},
        ]

    def test_reteiva_base_is_purchase_iva(self):
        result, _ = self._calculate(
            [_line("income", 1000000, 1)],
            [_rate("reteiva", "0.01")],
            self._assumption(), self._profile(reteiva_agent=True),
            events=self._iva_events(),
        )
        row = next(r for r in result["results"] if r["tax_type"] == "reteiva")
        self.assertEqual(row["taxable_base"], Decimal("285000.00"))
        self.assertEqual(row["tax_caused"], Decimal("2850.00"))
        self.assertEqual(row["calculation_trace"]["base_source"], "purchase_iva")

    def test_no_reteiva_row_when_not_agent_and_nothing_suffered(self):
        result, _ = self._calculate(
            [_line("income", 1000000, 1)],
            [_rate("reteiva", "0.01")],
            self._assumption(), self._profile(reteiva_agent=False),
            events=self._iva_events(),
        )
        self.assertNotIn("reteiva", {r["tax_type"] for r in result["results"]})

    def test_reteiva_row_when_not_agent_but_suffered_was_recorded(self):
        result, _ = self._calculate(
            [_line("income", 1000000, 1)],
            [_rate("reteiva", "0.01")],
            self._assumption(reteiva_suffered=Decimal("500")),
            self._profile(reteiva_agent=False),
            events=self._iva_events(),
        )
        row = next(r for r in result["results"] if r["tax_type"] == "reteiva")
        self.assertEqual(row["withholding_amount"], Decimal("500.00"))

    # ── Liquidación periódica de ICA / retención / reteIVA ─────────────

    def _calendar_row(self, tax_type, start, end, pay_month):
        return SimpleNamespace(
            tax_type=tax_type, is_active=True, regime=None,
            period_code=f'{tax_type}_P{pay_month}', sequence=pay_month,
            period_start=start, period_end=end,
            declaration_due_date=date(2027, pay_month, 20),
            payment_due_date=date(2027, pay_month, 20),
            payment_year=2027, notes=None,
        )

    def test_periodic_ica_uses_every_calendar_period(self):
        lines = [_line("income", 600000, 1), _line("income", 300000, 4)]
        calendars = [
            self._calendar_row("ica", date(2027, 1, 1), date(2027, 3, 31), 4),
            self._calendar_row("ica", date(2027, 4, 1), date(2027, 6, 30), 7),
        ]
        result, _ = self._calculate(
            lines, [_rate("ica", "0.002")], self._assumption(), self._profile(),
            calendars=calendars,
        )
        rows = [r for r in result["results"] if r["tax_type"] == "ica"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["taxable_base"] for r in rows],
                         [Decimal("600000.00"), Decimal("300000.00")])
        self.assertEqual([r["tax_caused"] for r in rows],
                         [Decimal("1200.00"), Decimal("600.00")])
        self.assertEqual([r["payment_date"] for r in rows],
                         [date(2027, 4, 20), date(2027, 7, 20)])

    def test_periodic_withholding_consumes_credit_in_period_order(self):
        lines = [_line("expense", 400000, 1), _line("purchase", 400000, 4)]
        calendars = [
            self._calendar_row("withholding", date(2027, 1, 1), date(2027, 3, 31), 4),
            self._calendar_row("withholding", date(2027, 4, 1), date(2027, 6, 30), 7),
        ]
        assumption = self._assumption(withholding_suffered=Decimal("300"))
        result, _ = self._calculate(
            lines, [_rate("withholding", "0.02")], assumption,
            self._profile(withholding_agent=True), calendars=calendars,
        )
        rows = [r for r in result["results"] if r["tax_type"] == "withholding"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["taxable_base"] for r in rows],
                         [Decimal("400000.00"), Decimal("400000.00")])
        self.assertEqual([r["withholding_amount"] for r in rows],
                         [Decimal("300.00"), Decimal("0.00")])
        self.assertEqual([r["balance_payable"] for r in rows],
                         [Decimal("7700.00"), Decimal("8000.00")])

    def test_periodic_reteiva_matches_purchase_iva_per_period(self):
        events = [
            {"date": "2027-01-10", "concept": "import_vat", "side": "deductible",
             "id_budget_line": 1, "amount": 190000.0},
            {"date": "2027-05-05", "concept": "nationalization_vat", "side": "deductible",
             "id_budget_line": 1, "amount": 40000.0},
        ]
        calendars = [
            self._calendar_row("reteiva", date(2027, 1, 1), date(2027, 2, 28), 3),
            self._calendar_row("reteiva", date(2027, 5, 1), date(2027, 6, 30), 6),
        ]
        result, _ = self._calculate(
            [_line("income", 1000000, 1)], [_rate("reteiva", "0.01")],
            self._assumption(), self._profile(reteiva_agent=True),
            events=events, calendars=calendars,
        )
        rows = [r for r in result["results"] if r["tax_type"] == "reteiva"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["taxable_base"] for r in rows],
                         [Decimal("190000.00"), Decimal("40000.00")])
        self.assertEqual([r["tax_caused"] for r in rows],
                         [Decimal("1900.00"), Decimal("400.00")])

    # ── Punto 2: comparación read-only ────────────────────────────────

    def test_persist_false_keeps_snapshots_and_never_commits(self):
        lines = [_line("income", 1000000, 1), _line("expense", 400000, 2)]
        rates = [_rate("income_ordinary", "0.30"), _rate("withholding", "0.02")]
        assumption = self._assumption()
        profile = self._profile()

        clear_readonly, add_readonly = MagicMock(), MagicMock()
        result, db_readonly = self._calculate(
            lines, rates, assumption, profile, persist=False,
            add_mock=add_readonly, clear_mock=clear_readonly,
        )
        self.assertTrue(result["results"])
        clear_readonly.assert_not_called()
        add_readonly.assert_not_called()
        self.assertEqual(db_readonly.commit_count, 0)

        clear_write, add_write = MagicMock(), MagicMock()
        _result_write, db_write = self._calculate(
            lines, rates, assumption, profile, persist=True,
            add_mock=add_write, clear_mock=clear_write,
        )
        clear_write.assert_called_once()
        self.assertGreater(add_write.call_count, 0)
        self.assertGreater(db_write.commit_count, 0)

    def test_regime_summary_aggregates_regime_taxes_only(self):
        from app.api.budget.taxPlanning import _regime_summary

        result = {"results": [
            {"tax_type": "income_ordinary", "taxable_base": Decimal("1000.00"),
             "tax_caused": Decimal("300.00"), "advance_amount": Decimal("100.00"),
             "withholding_amount": Decimal("50.00"), "balance_payable": Decimal("150.00")},
            # ICA applies to both regimes and must not inflate the comparison.
            {"tax_type": "ica", "taxable_base": Decimal("100000.00"),
             "tax_caused": Decimal("9999.00"), "advance_amount": Decimal("0"),
             "withholding_amount": Decimal("0"), "balance_payable": Decimal("0")},
        ]}
        summary = _regime_summary(result)
        self.assertEqual(summary["taxable_base"], Decimal("1000.00"))
        self.assertEqual(summary["tax_caused"], Decimal("300.00"))
        self.assertEqual(summary["withholdings"], Decimal("50.00"))
        self.assertEqual(summary["annual_total"], Decimal("250.00"))
        self.assertEqual(summary["effective_rate"], Decimal("0.300000"))


if __name__ == "__main__":
    unittest.main()
