"""
Budget Engine - Financial Logic Service

Implements the core financial engine for the Budget and Cash Flow module:

1. Cash Flow Projection:
   Crosses accounts receivable due dates against import calendars to
   predict liquidity and Cash Runway.

2. Budget Tracking:
   Provides aggregated comparisons (sums by month and cost center)
   between budget projections and actual execution.

3. What-If Scenarios:
   Implements budget cloning logic to create sandbox environments
   for simulating variations (e.g. freight increases, payment term
   changes) without affecting production data.
"""

# Python
from datetime import date
from typing import List, Optional, Dict, Any
from copy import deepcopy

# SQLAlchemy
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

# App
from app.models.budget import (
    CostCenter as CostCenterModel,
    ActualExpense as ActualExpenseModel,
    ActualCost as ActualCostModel,
    Budget as BudgetModel,
    BudgetLine as BudgetLineModel,
    AccountReceivable as AccountReceivableModel,
    PaymentLedger as PaymentLedgerModel,
    BudgetScenario as BudgetScenarioModel,
    AccountPayable as AccountPayableModel,
    PayableLedger as PayableLedgerModel,
)


class BudgetEngine:
    """
    Core financial engine for budget analysis, cash flow projection,
    and what-if scenario simulation.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # Cash Flow Projection
    # ──────────────────────────────────────────────

    def project_cash_flow(
        self,
        budget_year: int,
        id_budget: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Project monthly cash flow by crossing accounts receivable due dates
        against expected outflows from budget lines and accounts payable.

        Returns a list of monthly projections with:
        - month: int
        - expected_inflows: float (from accounts receivable)
        - expected_outflows: float (from budget expense lines + accounts payable)
        - net_cash_flow: float
        - cumulative_cash_flow: float

        Accounts payable balances are projected as cash outflows in the month
        of their due_date. To prevent double counting, budget_lines expense
        projections are suppressed for any (month, cost_center) pair that
        already has a real obligation in accounts_payable.

        Args:
            budget_year: Fiscal year for the projection.
            id_budget: Optional specific budget to use for outflows.
                       If None, uses the active budget for the year.
        """
        inflows_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}
        outflows_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}

        ar_rows = (
            self.db.query(
                extract("month", AccountReceivableModel.due_date).label("month"),
                func.coalesce(func.sum(AccountReceivableModel.balance), 0),
            )
            .filter(
                extract("year", AccountReceivableModel.due_date) == budget_year,
            )
            .group_by("month")
            .all()
        )
        for row in ar_rows:
            inflows_by_month[int(row.month)] += float(row[1])

        ap_rows = (
            self.db.query(
                extract("month", AccountPayableModel.due_date).label("month"),
                AccountPayableModel.id_cost_center,
                func.coalesce(func.sum(AccountPayableModel.balance), 0),
            )
            .filter(
                extract("year", AccountPayableModel.due_date) == budget_year,
            )
            .group_by("month", AccountPayableModel.id_cost_center)
            .all()
        )

        ap_keys = set()
        for row in ap_rows:
            month = int(row.month)
            outflows_by_month[month] += float(row[2])
            ap_keys.add((month, row.id_cost_center))

        bl_query = (
            self.db.query(
                BudgetLineModel.month,
                BudgetLineModel.id_cost_center,
                func.coalesce(func.sum(BudgetLineModel.projected_amount), 0),
            )
            .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
            .filter(
                BudgetModel.budget_year == budget_year,
                BudgetLineModel.line_type == "expense",
            )
        )
        if id_budget is not None:
            bl_query = bl_query.filter(BudgetLineModel.id_budget == id_budget)

        bl_rows = (
            bl_query.group_by(BudgetLineModel.month, BudgetLineModel.id_cost_center)
            .all()
        )
        for row in bl_rows:
            month = int(row.month)
            if (month, row.id_cost_center) not in ap_keys:
                outflows_by_month[month] += float(row[2])

        result = []
        cumulative = 0.0
        for month in range(1, 13):
            net = inflows_by_month[month] - outflows_by_month[month]
            cumulative += net
            result.append({
                "month": month,
                "expected_inflows": round(inflows_by_month[month], 2),
                "expected_outflows": round(outflows_by_month[month], 2),
                "net_cash_flow": round(net, 2),
                "cumulative_cash_flow": round(cumulative, 2),
            })
        return result

    # ──────────────────────────────────────────────
    # Budget Tracking (Budget vs Actual)
    # ──────────────────────────────────────────────

    def get_budget_vs_actual(
        self,
        id_budget: int,
        id_cost_center: Optional[int] = None,
        month: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Compare budget projections against actual execution.

        Returns a list of records with:
        - id_cost_center: int
        - cost_center_code: str
        - cost_center_name: str
        - month: int
        - budgeted_amount: float
        - actual_amount: float
        - variance: float
        - variance_percentage: Optional[float]

        Args:
            id_budget: The budget to analyze.
            id_cost_center: Optional filter by cost center.
            month: Optional filter by month (1-12).
        """
        # TODO: Implement budget vs actual comparison
        # 1. Get budget_lines for the budget, grouped by cost_center and month
        # 2. Get actual_expenses + actual_costs, grouped by cost_center and month
        # 3. Join and calculate variance
        return []

    def get_budget_tracking_summary(self, id_budget: int) -> Dict[str, Any]:
        """
        Get a complete budget tracking summary.

        Returns:
        - id_budget: int
        - budget_name: str
        - total_budgeted: float
        - total_actual: float
        - total_variance: float
        - execution_percentage: Optional[float]
        - by_month: List[BudgetVsActual]
        """
        # TODO: Implement tracking summary
        return {}

    # ──────────────────────────────────────────────
    # What-If Scenarios
    # ──────────────────────────────────────────────

    def clone_budget_for_scenario(
        self,
        id_budget: int,
        scenario_name: str,
    ) -> Optional[BudgetModel]:
        """
        Clone a budget into a sandbox for what-if simulation.

        Creates a new budget record with:
        - is_scenario = True
        - parent_budget_id = original budget
        - status = 'draft'
        All budget lines from the original are duplicated into the clone.

        Args:
            id_budget: The source budget to clone.
            scenario_name: Name for the scenario clone.

        Returns:
            The newly created scenario budget, or None if source not found.
        """
        # TODO: Implement budget cloning
        # 1. Fetch the original budget
        # 2. Create a new budget with is_scenario=True
        # 3. Copy all budget_lines to the new budget
        # 4. Return the cloned budget
        return None

    def apply_scenario_parameters(
        self,
        id_budget_scenario: int,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply scenario parameters to a cloned budget and compute results.

        Supported parameter types:
        - freight_increase: Percentage increase in freight costs
        - payment_terms_change: Adjust due dates by N days
        - cost_reduction: Percentage reduction in specific cost centers
        - revenue_adjustment: Percentage change in income projections

        Args:
            id_budget_scenario: The scenario budget to modify.
            parameters: Dict of parameter names and values.

        Returns:
            Dict with scenario results and impact analysis.
        """
        # TODO: Implement parameter application logic
        return {}

    def compare_scenarios(
        self,
        id_budget_base: int,
        id_scenario_a: int,
        id_scenario_b: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compare one or two scenarios against the base budget.

        Returns a side-by-side comparison of key metrics:
        - Total budgeted vs projected
        - Variance by cost center
        - Cash flow impact
        - Risk indicators

        Args:
            id_budget_base: The base (production) budget.
            id_scenario_a: First scenario to compare.
            id_scenario_b: Optional second scenario for A/B comparison.
        """
        # TODO: Implement scenario comparison
        return {}

    # ──────────────────────────────────────────────
    # Aggregation Helpers
    # ──────────────────────────────────────────────

    def get_monthly_expense_summary(
        self,
        id_cost_center: Optional[int] = None,
        year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get monthly expense summary aggregated by cost center.

        Returns list of dicts with: month, total_expenses, total_costs.
        """
        # TODO: Implement monthly aggregation
        return []

    def get_cost_center_summary(
        self,
        year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get cost center summary with total budgeted vs actual.

        Returns list of dicts with: cost_center info, budgeted_total,
        actual_total, variance.
        """
        # TODO: Implement cost center aggregation
        return []
