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
from app.core.constants import TAX_RATE
from app.models import (
    Invoice as InvoiceModel,
    InvoiceDetail as InvoiceDetailModel,
    Reference as ReferenceModel,
    Brand as BrandModel,
)
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
    LineCostRate as LineCostRateModel,
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
        - expected_inflows: float (cash inflows with tax)
        - expected_outflows: float (fixed expenses + variable expenses + accounts payable)
        - net_cash_flow: float
        - cumulative_cash_flow: float

        Income projections in budget_lines are NET (without tax).
        Cash inflows include tax: net_income * (1 + TAX_RATE).

        Args:
            budget_year: Fiscal year for the projection.
            id_budget: Optional specific budget to use for outflows.
                       If None, uses the active budget for the year.
        """
        inflows_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}
        outflows_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}
        net_income_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}

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
            net_income_by_month[int(row.month)] += float(row[1])

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

        income_query = (
            self.db.query(
                extract("month", BudgetLineModel.budget_date).label("budget_month"),
                func.coalesce(func.sum(BudgetLineModel.projected_amount), 0),
            )
            .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
            .filter(
                BudgetModel.budget_year == budget_year,
                BudgetLineModel.line_type == "income",
            )
        )
        if id_budget is not None:
            income_query = income_query.filter(BudgetLineModel.id_budget == id_budget)

        income_rows = income_query.group_by("budget_month").all()
        for row in income_rows:
            net_income_by_month[int(row.budget_month)] += float(row[1])

        for month in range(1, 13):
            inflows_by_month[month] = net_income_by_month[month] * (1 + TAX_RATE)

        fixed_expense_query = (
            self.db.query(
                func.coalesce(
                    extract("month", BudgetLineModel.payment_date),
                    extract("month", BudgetLineModel.budget_date),
                ).label("payment_month"),
                BudgetLineModel.id_cost_center,
                func.coalesce(func.sum(BudgetLineModel.projected_amount), 0),
            )
            .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
            .filter(
                BudgetModel.budget_year == budget_year,
                BudgetLineModel.line_type == "expense",
                BudgetLineModel.behavior_type == "fixed",
            )
        )
        if id_budget is not None:
            fixed_expense_query = fixed_expense_query.filter(BudgetLineModel.id_budget == id_budget)

        fixed_rows = (
            fixed_expense_query.group_by("payment_month", BudgetLineModel.id_cost_center)
            .all()
        )
        for row in fixed_rows:
            month = int(row.payment_month)
            if (month, row.id_cost_center) not in ap_keys:
                outflows_by_month[month] += float(row[2])

        variable_sales_query = (
            self.db.query(
                func.coalesce(
                    extract("month", BudgetLineModel.payment_date),
                    extract("month", BudgetLineModel.budget_date),
                ).label("payment_month"),
                BudgetLineModel.variable_rate,
                func.coalesce(func.sum(BudgetLineModel.projected_amount), 0),
            )
            .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
            .filter(
                BudgetModel.budget_year == budget_year,
                BudgetLineModel.line_type == "expense",
                BudgetLineModel.behavior_type == "variable_sales",
            )
        )
        if id_budget is not None:
            variable_sales_query = variable_sales_query.filter(BudgetLineModel.id_budget == id_budget)

        variable_sales_rows = variable_sales_query.group_by("payment_month", BudgetLineModel.variable_rate).all()
        for row in variable_sales_rows:
            month = int(row.payment_month)
            rate = float(row.variable_rate) if row.variable_rate else 0.0
            variable_cost = float(row[2]) * rate
            outflows_by_month[month] += variable_cost

        variable_receivables_query = (
            self.db.query(
                func.coalesce(
                    extract("month", BudgetLineModel.payment_date),
                    extract("month", BudgetLineModel.budget_date),
                ).label("payment_month"),
                BudgetLineModel.variable_rate,
            )
            .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
            .filter(
                BudgetModel.budget_year == budget_year,
                BudgetLineModel.line_type == "expense",
                BudgetLineModel.behavior_type == "variable_receivables",
            )
        )
        if id_budget is not None:
            variable_receivables_query = variable_receivables_query.filter(BudgetLineModel.id_budget == id_budget)

        variable_receivables_rows = variable_receivables_query.all()
        for row in variable_receivables_rows:
            month = int(row.payment_month)
            rate = float(row.variable_rate) if row.variable_rate else 0.0
            variable_cost = net_income_by_month[month] * rate
            outflows_by_month[month] += variable_cost

        result = []
        cumulative = 0.0
        for month in range(1, 13):
            net = inflows_by_month[month] - outflows_by_month[month]
            cumulative += net
            result.append({
                "payment_month": month,
                "expected_inflows": round(inflows_by_month[month], 2),
                "expected_outflows": round(outflows_by_month[month], 2),
                "net_cash_flow": round(net, 2),
                "cumulative_cash_flow": round(cumulative, 2),
            })
        return result

    # ──────────────────────────────────────────────
    # Pilar 1 — Accrual P&L (spec backend.02_09)
    # ──────────────────────────────────────────────

    def _budget_rows(
        self,
        resolved_id: int,
        date_from: date,
        date_to: date,
        line_type: str,
        id_cost_center: Optional[int],
        id_line: Optional[int],
    ) -> List[Any]:
        """Q4/Q5 helper: budget projections grouped per (cost center, line).

        line_type is compared as a plain string ("income" | "expense"),
        matching the existing project_cash_flow pattern. All behavior_type
        rows are summed (BR-16): variable_rate is cash-flow mechanics only.
        The id_line filter narrows INCOME budget rows through the cost
        center's line mapping (cost_centers.id_line, BR-10); expense budget
        has no line dimension (A-7), so the filter is ignored there.
        """
        q = (self.db.query(
                BudgetLineModel.id_cost_center,
                CostCenterModel.id_line,
                func.coalesce(func.sum(BudgetLineModel.projected_amount), 0.0))
             .join(BudgetModel, BudgetLineModel.id_budget == BudgetModel.id_budget)
             .join(CostCenterModel, BudgetLineModel.id_cost_center == CostCenterModel.id_cost_center)
             .filter(BudgetModel.id_budget == resolved_id,
                     BudgetLineModel.line_type == line_type,
                     BudgetLineModel.budget_date >= date_from,
                     BudgetLineModel.budget_date <= date_to))
        if id_cost_center is not None:
            q = q.filter(BudgetLineModel.id_cost_center == id_cost_center)
        if id_line is not None and line_type == "income":
            q = q.filter(CostCenterModel.id_line == id_line)
        return q.group_by(
            BudgetLineModel.id_cost_center, CostCenterModel.id_line
        ).all()

    def get_pnl(
        self,
        date_from: date,
        date_to: date,
        id_budget: Optional[int] = None,
        id_cost_center: Optional[int] = None,
        id_line: Optional[int] = None,
        id_reference: Optional[int] = None,
        include_breakdown: bool = False,
    ) -> Dict[str, Any]:
        """Build the accrual P&L (Real vs Presupuestado vs Varianza).

        Pure read-only aggregation layer (BR-19): no add/flush/commit/delete
        anywhere in this method. Queries Q0-Q7 per spec §5.2; derived values,
        favorability chain (BR-8) and variance conventions (D-4) per §5.3;
        filter semantics per §5.4.
        """
        slice_mode = (id_line is not None) or (id_reference is not None)
        warnings: List[str] = []
        not_filterable: List[str] = []

        # ── Q0: resolve the comparison budget (D-3 / BR-17) ────────────
        budget_row = None
        if id_budget is not None:
            # Missing id_budget is a 404 at the endpoint (§6.1 E-2).
            budget_row = self.db.query(BudgetModel).filter(
                BudgetModel.id_budget == id_budget).first()
        else:
            candidates = (self.db.query(BudgetModel)
                          .filter(BudgetModel.budget_year == date_to.year,
                                  BudgetModel.status == "active",
                                  BudgetModel.is_scenario.is_(False))
                          .order_by(BudgetModel.id_budget).all())
            if candidates:
                budget_row = candidates[0]
                if len(candidates) > 1:
                    warnings.append(
                        "More than one active non-scenario budget for "
                        f"{date_to.year}; using the lowest id_budget "
                        f"({budget_row.id_budget})"
                    )
            else:
                warnings.append(
                    f"No active non-scenario budget for {date_to.year}"
                )

        if budget_row is not None and id_budget is not None and budget_row.is_scenario:
            warnings.append("Comparing against scenario budget")

        if date_from.year != date_to.year:
            warnings.append(
                "period crosses fiscal years; budget scoped to "
                f"year({date_to.year})"
            )

        resolved_id: Optional[int] = None
        budget_source: Optional[Dict[str, Any]] = None
        if budget_row is not None:
            resolved_id = budget_row.id_budget
            budget_source = {
                "id_budget": budget_row.id_budget,
                "budget_name": budget_row.budget_name,
                "status": budget_row.status,
            }

        # ── Q1: actual revenues (BR-1/BR-2/BR-3/BR-4) ──────────────────
        if not slice_mode:
            # Q1a — consolidated: header level, canonical (SIIGO-reconcilable)
            revenues_actual = float(self.db.query(
                func.coalesce(func.sum(InvoiceModel.total_without_tax), 0.0)
            ).filter(
                InvoiceModel.invoice_date >= date_from,
                InvoiceModel.invoice_date <= date_to,
            ).scalar())
        else:
            # Q1b — slice: detail level through the reference->brand->line map
            q = (self.db.query(
                    func.coalesce(func.sum(InvoiceDetailModel.value_without_tax), 0.0))
                 .join(InvoiceModel, InvoiceDetailModel.id_invoice == InvoiceModel.id_invoice)
                 .join(ReferenceModel, InvoiceDetailModel.id_reference == ReferenceModel.id_reference)
                 .join(BrandModel, ReferenceModel.id_brand == BrandModel.id_brand)
                 .filter(InvoiceModel.invoice_date >= date_from,
                         InvoiceModel.invoice_date <= date_to))
            if id_reference is not None:
                q = q.filter(InvoiceDetailModel.id_reference == id_reference)
            if id_line is not None:
                q = q.filter(BrandModel.id_line == id_line)
            revenues_actual = float(q.scalar())

        # D-1: a negative invoice whose details lack a product reference is
        # invisible to the slice JOINs (it only affects consolidated
        # revenues); report the count whenever a slice is requested.
        if slice_mode:
            neg_excluded = (self.db.query(
                func.count(func.distinct(InvoiceModel.id_invoice)))
                .join(InvoiceDetailModel,
                      InvoiceDetailModel.id_invoice == InvoiceModel.id_invoice)
                .filter(InvoiceModel.invoice_date >= date_from,
                        InvoiceModel.invoice_date <= date_to,
                        InvoiceModel.total_without_tax < 0,
                        InvoiceDetailModel.id_reference.is_(None))
                .scalar())
            if neg_excluded:
                warnings.append(
                    f"{neg_excluded} negative invoice(s) with details lacking "
                    "a product reference were excluded from this slice; they "
                    "only affect consolidated revenues"
                )

        # ── Q2: actual COGS (BR-5) ──────────────────────────────────────
        q = (self.db.query(func.coalesce(func.sum(ActualCostModel.amount), 0.0))
             .filter(ActualCostModel.cost_date >= date_from,
                     ActualCostModel.cost_date <= date_to))
        if id_cost_center is not None:
            q = q.filter(ActualCostModel.id_cost_center == id_cost_center)
        if id_reference is not None:
            q = q.filter(ActualCostModel.id_reference == id_reference)
        if id_line is not None:
            q = (q.join(ReferenceModel,
                        ActualCostModel.id_reference == ReferenceModel.id_reference)
                  .join(BrandModel,
                        ReferenceModel.id_brand == BrandModel.id_brand)
                  .filter(BrandModel.id_line == id_line))
        cogs_actual = float(q.scalar())

        # ── Q3: actual OPEX — null in slice mode (BR-10/BR-11) ─────────
        opex_actual: Optional[float] = None
        breakdown: Optional[List[Dict[str, Any]]] = None
        if not slice_mode:
            if include_breakdown:
                rows = (self.db.query(
                            ActualExpenseModel.expense_type,
                            func.coalesce(func.sum(ActualExpenseModel.amount), 0.0))
                        .filter(ActualExpenseModel.expense_date >= date_from,
                                ActualExpenseModel.expense_date <= date_to))
                if id_cost_center is not None:
                    rows = rows.filter(ActualExpenseModel.id_cost_center == id_cost_center)
                grouped = rows.group_by(ActualExpenseModel.expense_type).all()
                breakdown = [
                    {"category": t, "actual": round(float(a), 2)}
                    for t, a in grouped
                ]
                opex_actual = round(sum(float(a) for _t, a in grouped), 2)
            else:
                q3 = self.db.query(
                    func.coalesce(func.sum(ActualExpenseModel.amount), 0.0)
                ).filter(ActualExpenseModel.expense_date >= date_from,
                         ActualExpenseModel.expense_date <= date_to)
                if id_cost_center is not None:
                    q3 = q3.filter(ActualExpenseModel.id_cost_center == id_cost_center)
                opex_actual = float(q3.scalar())

        # ── Q4/Q5: budget rows per cost center (§5.2 invocation rules) ──
        # id_reference kills the budget side entirely (BR-11: the plan does
        # not know references); id_line only narrows Q4 through the CECO map.
        q4_ran = resolved_id is not None and id_reference is None
        q5_ran = q4_ran and not slice_mode

        income_rows: List[Any] = []
        expense_rows: List[Any] = []
        if q4_ran:
            income_rows = self._budget_rows(
                resolved_id, date_from, date_to, "income", id_cost_center, id_line)
        if q5_ran:
            expense_rows = self._budget_rows(
                resolved_id, date_from, date_to, "expense", id_cost_center, None)

        revenues_budget = (
            round(float(sum(r[2] for r in income_rows)), 2) if q4_ran else None
        )
        opex_budget = (
            round(float(sum(r[2] for r in expense_rows)), 2) if q5_ran else None
        )

        # ── Q6: active rates at the period end (BR-14) + cogs.budget ────
        rates = (self.db.query(LineCostRateModel)
                 .filter(LineCostRateModel.is_active.is_(True),
                         LineCostRateModel.date_from <= date_to,
                         LineCostRateModel.date_to >= date_to)
                 .order_by(LineCostRateModel.id_line_cost_rate.desc())
                 .all())
        pct_by_line: Dict[int, float] = {}
        fallback_pct: Optional[float] = None
        for r in rates:
            if r.id_line is None:
                fallback_pct = float(r.cogs_pct) if fallback_pct is None else fallback_pct
            else:
                pct_by_line.setdefault(r.id_line, float(r.cogs_pct))

        # D-2/BR-7 chain: line rate -> global fallback -> exclusion (BR-15),
        # with the per-CECO audit trace (D-6/BR-21) and Q7 code map.
        cogs_budget: Optional[float] = None
        cogs_trace: List[Dict[str, Any]] = []
        if q4_ran and income_rows:
            cc_codes = dict(self.db.query(
                CostCenterModel.id_cost_center,
                CostCenterModel.cost_center_code).all())  # Q7
            total = 0.0
            applied = False
            for cc, line, amount in income_rows:
                pct = pct_by_line.get(line) if line is not None else None
                source = "line"
                if pct is None:
                    pct, source = fallback_pct, "global"
                if pct is None:
                    warnings.append(
                        f"Cost center {cc} has income budget "
                        f"{float(amount):.2f} and no applicable cost rate; "
                        "excluded from cogs.budget"
                    )
                    continue
                contribution = round(float(amount) * pct / 100.0, 2)
                total += contribution
                applied = True
                cogs_trace.append({
                    "id_cost_center": cc,
                    "cost_center_code": cc_codes.get(cc),
                    "id_line": line,
                    "pct": pct,
                    "source": source,
                    "income_budget": round(float(amount), 2),
                    "cogs_contribution": contribution,
                })
            cogs_budget = round(total, 2) if applied else None
            if cogs_budget is None:
                warnings.append(
                    "No cost rate configured (line or global) for the "
                    "period: cogs.budget is null"
                )

        # ── Derived values (§5.3, BR-6/BR-8, null-safe) ─────────────────
        gross_actual = round(revenues_actual - cogs_actual, 2)
        opex_a = opex_actual if opex_actual is not None else 0.0
        operating_actual = round(gross_actual - opex_a, 2)  # slice: == gross (BR-11)

        gross_budget = (
            round(revenues_budget - cogs_budget, 2)
            if revenues_budget is not None and cogs_budget is not None
            else None
        )
        operating_budget = (
            round(gross_budget - opex_budget, 2)
            if gross_budget is not None and opex_budget is not None
            else None
        )

        # ── meta: not_filterable (BR-9/BR-10/A-7) ────────────────────────
        if id_cost_center is not None:
            not_filterable.append("revenues (no cost-center dimension)")
        if slice_mode:
            not_filterable.append("opex (no line/reference dimension)")
            not_filterable.append("opex_budget (no slice support in v1)")
            if id_reference is not None:
                not_filterable.append("revenues_budget (no reference dimension)")
                not_filterable.append("cogs_budget (no reference dimension)")

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "pnl_statement": {
                "revenues": self._pnl_comparison(
                    revenues_actual, revenues_budget, favorable_up=True),
                "cogs": self._pnl_comparison(
                    cogs_actual, cogs_budget, favorable_up=False),
                "gross_profit": self._pnl_profit(
                    gross_actual, gross_budget,
                    revenues_actual, revenues_budget),
                "opex": {
                    **self._pnl_comparison(
                        opex_actual, opex_budget, favorable_up=False),
                    "breakdown": breakdown,
                },
                "operating_profit": self._pnl_profit(
                    operating_actual, operating_budget,
                    revenues_actual, revenues_budget),
            },
            "meta": {
                "mode": "slice" if slice_mode else "consolidated",
                "budget_source": budget_source,
                "filters": {
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "id_budget": id_budget,
                    "id_cost_center": id_cost_center,
                    "id_line": id_line,
                    "id_reference": id_reference,
                    "include_breakdown": include_breakdown,
                },
                "not_filterable": not_filterable,
                "cogs_budget_trace": cogs_trace,
                "warnings": warnings,
            },
        }

    @staticmethod
    def _pnl_comparison(
        actual: Optional[float],
        budget: Optional[float],
        favorable_up: bool,
    ) -> Dict[str, Any]:
        """D-4 favorability variances: revenues/profits = actual - budget;
        cogs/opex = budget - actual. variance_pct null when budget null or 0.
        Values 2 dec (§5.3)."""
        variance: Optional[float] = None
        variance_pct: Optional[float] = None
        if actual is not None and budget is not None:
            variance = round(
                (actual - budget) if favorable_up else (budget - actual), 2)
            if budget != 0:
                variance_pct = round(variance / abs(budget) * 100.0, 2)
        return {
            "actual": actual,
            "budget": budget,
            "variance": variance,
            "variance_pct": variance_pct,
        }

    @staticmethod
    def _pnl_profit(
        actual: Optional[float],
        budget: Optional[float],
        revenue_actual: float,
        revenue_budget: Optional[float],
    ) -> Dict[str, Any]:
        """Profit row = comparison (actual - budget, favorable up) plus
        margins over the real figures (A-9, 1 dec) and the budgeted margin
        (additive). Null margin when the revenue denominator is null or 0."""
        row = BudgetEngine._pnl_comparison(actual, budget, favorable_up=True)
        row["margin_pct"] = (
            round(actual / revenue_actual * 100.0, 1)
            if actual is not None and revenue_actual
            else None
        )
        row["margin_pct_budget"] = (
            round(budget / revenue_budget * 100.0, 1)
            if budget is not None and revenue_budget
            else None
        )
        return row

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
