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
from datetime import date, timedelta
from typing import List, Optional, Dict, Any
from copy import deepcopy

# SQLAlchemy
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, case

# App
from app.core.constants import TAX_RATE
from app.models import (
    Invoice as InvoiceModel,
    InvoiceDetail as InvoiceDetailModel,
    Reference as ReferenceModel,
    Brand as BrandModel,
    Order as OrderModel,
    CustomerTrip as CustomerTripModel,
    Customer as CustomerModel,
    User as UserModel,
    Line as LineModel,
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
    CommissionRate as CommissionRateModel,
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

    # ──────────────────────────────────────────────
    # Pilar 2 — Cash Flow (spec backend.02_10)
    # ──────────────────────────────────────────────

    def _cash_buckets(self, date_from: date, date_to: date,
                      granularity: str) -> List[tuple]:
        """Regresa [(label_iso, coverage_start, coverage_end)] cubriendo la ventana.

        weekly = lunes ISO; label = inicio REAL del bucket de calendario (puede ser
        anterior a date_from cuando la ventana abre a mitad de semana/mes, BR-34);
        la cobertura se recorta a [date_from, date_to]. Cero-fill garantizado: no
        se consulta generate_series; los buckets sin movimientos existen igual."""
        buckets: List[tuple] = []
        if granularity == "daily":
            d = date_from
            while d <= date_to:
                buckets.append((d.isoformat(), d, d))
                d += timedelta(days=1)
        elif granularity == "weekly":
            monday = date_from - timedelta(days=date_from.weekday())
            while monday <= date_to:
                sunday = monday + timedelta(days=6)
                buckets.append((monday.isoformat(),
                                max(monday, date_from), min(sunday, date_to)))
                monday += timedelta(days=7)
        else:  # monthly
            y, m = date_from.year, date_from.month
            while (y, m) <= (date_to.year, date_to.month):
                start = date(y, m, 1)
                nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                buckets.append((start.isoformat(),
                                max(start, date_from),
                                min(nxt - timedelta(days=1), date_to)))
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return buckets

    def get_cash_flow(
        self,
        date_from: date,
        date_to: date,
        granularity: str = "monthly",              # daily | weekly | monthly (BR-34)
        id_budget: Optional[int] = None,           # D-7 (misma semantica que get_pnl)
        initial_balance: Optional[float] = None,   # D-4 (parameter manda)
        outflow_source: str = "both",              # budget | ap | both (D-1)
        overdue_as: str = "clamp_cutoff",          # clamp_cutoff | first_bucket | exclude (D-2)
        cutoff_date: Optional[date] = None,        # as-of; default date.today() (D-3)
    ) -> Dict[str, Any]:
        """Build the liquidity curve (Pilar 2): real cash vs AR/AP/budget projection.

        Pure read-only aggregation layer (BR-32): no add/flush/commit/delete
        anywhere in this method. Queries Q0-Q5 per spec §5.4; bucket assembly,
        status split (BR-24) and running accumulation (BR-35) per §5.5; overlap
        warnings (D-1/BR-29) per §5.6. project_cash_flow (legacy) is untouched.
        """
        cutoff = cutoff_date or date.today()       # BR-37 (UTC del contenedor)
        slice_lo = max(date_from, cutoff)          # piso de anclas proyectadas (BR-26/27)
        warnings: List[str] = []

        # ── Q0: resolve the comparison budget (D-7 / BR-31, shared literals
        #        with get_pnl; sin presupuesto => Q5 = 0.0, nunca null) ─────
        budget_row = None
        if id_budget is not None:
            # Missing id_budget is a 404 at the endpoint (§10 E-CF-2).
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

        resolved_id: Optional[int] = None
        budget_source: Optional[Dict[str, Any]] = None
        if budget_row is not None:
            resolved_id = budget_row.id_budget
            budget_source = {
                "id_budget": budget_row.id_budget,
                "budget_name": budget_row.budget_name,
                "status": budget_row.status,
            }

        # ── Buckets: cero-fill en Python, nunca generate_series (D-6/BR-33) ──
        buckets = self._cash_buckets(date_from, date_to, granularity)

        # ── Q1: real CASH movements in the window (BR-22/BR-23/BR-25) ───────
        _signed = case(
            (PaymentLedgerModel.cash_flow == "in", func.abs(PaymentLedgerModel.payment_amount)),
            (PaymentLedgerModel.cash_flow == "out", -func.abs(PaymentLedgerModel.payment_amount)),
            else_=0.0,
        )
        real_rows = (self.db.query(
                PaymentLedgerModel.payment_date,
                func.coalesce(func.sum(case(
                    (PaymentLedgerModel.cash_flow == "in",
                     func.abs(PaymentLedgerModel.payment_amount)), else_=0.0)), 0.0),
                func.coalesce(func.sum(case(
                    (PaymentLedgerModel.cash_flow == "out",
                     func.abs(PaymentLedgerModel.payment_amount)), else_=0.0)), 0.0))
             .filter(PaymentLedgerModel.transaction_nature == "CASH",
                     PaymentLedgerModel.cash_flow.in_(("in", "out")),   # excluye NULL (BR-22)
                     PaymentLedgerModel.payment_date >= date_from,
                     PaymentLedgerModel.payment_date <= date_to)
             .group_by(PaymentLedgerModel.payment_date)
             .all())
        # -> {date: (inflows, outflows_abs)}; cada monto entra en su bucket por
        # cobertura (BR-25: una fila real futura cuenta como real igual)
        real_by_day: Dict[date, tuple] = {
            r[0]: (float(r[1]), float(r[2])) for r in real_rows
        }

        # ── Q2: derived starting balance (D-4/BR-30; omitido si llega el
        #        parametro, que manda sobre la base ledger-relativa) ──────────
        if initial_balance is not None:
            starting_balance = float(initial_balance)
            initial_balance_source = "provided"
        else:
            starting_balance = float(self.db.query(
                func.coalesce(func.sum(_signed), 0.0)
            ).filter(
                PaymentLedgerModel.transaction_nature == "CASH",
                PaymentLedgerModel.cash_flow.in_(("in", "out")),
                PaymentLedgerModel.payment_date < date_from,
            ).scalar())
            initial_balance_source = "derived_from_ledger"
            warnings.append("starting_balance is ledger-relative: set "
                            "initial_balance for the true bank position")

        # ── Q3: projected inflows = AR deudor en [slice_lo, date_to] (BR-26) ──
        # `balance` ya es neto (settle del CRUD 02_08); jamas filtrar por status.
        ar_rows = (self.db.query(
                AccountReceivableModel.due_date,
                func.sum(AccountReceivableModel.balance))
             .filter(AccountReceivableModel.balance > 0,        # saldo deudor (A-6)
                     AccountReceivableModel.due_date >= slice_lo,
                     AccountReceivableModel.due_date <= date_to)
             .group_by(AccountReceivableModel.due_date)
             .all())
        ar_by_day: Dict[date, float] = {r[0]: float(r[1]) for r in ar_rows}

        # ── Q4: AP outflows anchored per overdue_as (D-2/BR-28; skipped when
        #        outflow_source=budget per §5.4 invocation rules) ──────────────
        ap_anchored: List[tuple] = []       # (anchor_date, id_cost_center, amount)
        overdue_outflows = 0.0
        n_excluded = 0
        if outflow_source in ("ap", "both"):
            ap_rows = (self.db.query(
                    AccountPayableModel.id_cost_center,
                    AccountPayableModel.due_date,
                    AccountPayableModel.balance)
                 .filter(AccountPayableModel.balance > 0)   # nunca por status (§13)
                 .all())
            for cc, due, bal in ap_rows:
                if due >= cutoff:
                    anchor = due
                elif overdue_as == "clamp_cutoff":
                    anchor = cutoff
                    overdue_outflows += float(bal)
                elif overdue_as == "first_bucket":
                    anchor = date_from
                    overdue_outflows += float(bal)
                else:                            # exclude
                    overdue_outflows += float(bal)   # se reporta el monto excluido igual
                    n_excluded += 1
                    continue
                if date_from <= anchor <= date_to:
                    ap_anchored.append((anchor, cc, float(bal)))
            if overdue_as == "exclude" and overdue_outflows:
                warnings.append(f"{n_excluded} past-due payable obligation(s) "
                                "excluded (overdue_as=exclude)")

        # ── Q5: budget expense outflows (BR-27; skipped when outflow_source=ap
        #        or no resolved budget => salidas 0.0, no null, D-7) ──────────
        bud_anchored: List[tuple] = []      # (anchor_date, id_cost_center, amount)
        if outflow_source in ("budget", "both") and resolved_id is not None:
            bud_rows = (self.db.query(
                    BudgetLineModel.id_cost_center,
                    func.coalesce(BudgetLineModel.payment_date,
                                  BudgetLineModel.budget_date).label("anchor"),
                    func.sum(BudgetLineModel.projected_amount))
                 .filter(BudgetLineModel.id_budget == resolved_id,
                         BudgetLineModel.line_type == "expense",
                         func.coalesce(BudgetLineModel.payment_date,
                                       BudgetLineModel.budget_date) >= slice_lo,
                         func.coalesce(BudgetLineModel.payment_date,
                                       BudgetLineModel.budget_date) <= date_to)
                 .group_by(BudgetLineModel.id_cost_center, "anchor")
                 .all())
            bud_anchored = [(r[1], r[0], float(r[2])) for r in bud_rows]

        # ── Imputation: cada ancla cae en el bucket que la cubre (§5.5) ─────
        def _cover(d: date) -> Optional[str]:
            for label, b_start, b_end in buckets:
                if b_start <= d <= b_end:
                    return label
            return None

        inflow_by_bucket: Dict[str, float] = {label: 0.0 for label, _s, _e in buckets}
        outflow_by_bucket: Dict[str, float] = {label: 0.0 for label, _s, _e in buckets}
        budget_side: Dict[tuple, float] = {}    # (cc, label) totals for overlap (BR-29)
        ap_side: Dict[tuple, float] = {}

        for day, (rin, rout) in real_by_day.items():
            label = _cover(day)
            inflow_by_bucket[label] += rin
            outflow_by_bucket[label] += rout
        for day, amount in ar_by_day.items():
            inflow_by_bucket[_cover(day)] += amount
        for anchor, cc, amount in bud_anchored:
            label = _cover(anchor)
            outflow_by_bucket[label] += amount
            budget_side[(cc, label)] = budget_side.get((cc, label), 0.0) + amount
        for anchor, cc, amount in ap_anchored:
            label = _cover(anchor)
            outflow_by_bucket[label] += amount
            ap_side[(cc, label)] = ap_side.get((cc, label), 0.0) + amount

        # ── Overlap detection, only in both mode (D-1/BR-29): se denuncia,
        #        nunca se deduplica; orden estable por (cc, label) ────────────
        if outflow_source == "both":
            for key in sorted(set(budget_side) & set(ap_side)):
                cc, label = key
                warnings.append(
                    f"Potential outflow overlap (cost center {cc} in {label}): "
                    f"budget expense {budget_side[key]:.2f} and payable obligation "
                    f"{ap_side[key]:.2f} may double-count"
                )

        # ── Assembly: status split (BR-24), magnitudes abs con signo de
        #        payload (BR-23/A-6), running sum (BR-35), 2 dec (BR-38) ──────
        points: List[Dict[str, Any]] = []
        starting_balance = round(starting_balance, 2)
        accumulated = starting_balance
        for label, b_start, b_end in buckets:
            inflow = inflow_by_bucket[label]
            outflow = outflow_by_bucket[label]
            status = "actual" if b_end < cutoff else "projected"
            net = round(inflow - outflow, 2)
            accumulated = round(accumulated + net, 2)
            points.append({
                "period": label, "status": status,
                "inflows": round(inflow, 2),
                "outflows": -round(outflow, 2),     # payload SIEMPRE negativo (A-6)
                "net_flow": net,
                "accumulated_balance": accumulated,
            })

        return {
            "summary": {
                "starting_balance": starting_balance,
                "ending_balance": accumulated,
                "net_flow": round(accumulated - starting_balance, 2),
            },
            "time_series": points,
            "meta": {
                "granularity": granularity,
                "cutoff": cutoff.isoformat(),
                "initial_balance_source": initial_balance_source,
                "outflow_source": outflow_source,
                "overdue_as": overdue_as,
                "budget_source": budget_source,
                "overdue_outflows": round(overdue_outflows, 2),
                "filters": {
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "granularity": granularity,
                    "id_budget": id_budget,
                    "initial_balance": initial_balance,
                    "outflow_source": outflow_source,
                    "overdue_as": overdue_as,
                    "cutoff_date": cutoff_date.isoformat() if cutoff_date is not None else None,
                },
                "warnings": warnings,
            },
        }

    # ──────────────────────────────────────────────
    # Pilar 3 — Commission Engine (spec backend.02_11)
    # ──────────────────────────────────────────────

    @staticmethod
    def _business_period(period: str) -> tuple:
        """'2026-09' -> (date(2026, 8, 26), date(2026, 9, 25)). Bordes inclusivos.
        Enero deriva del diciembre del ano anterior. Valida formato YYYY-MM
        (E-CM-3 422 si no parsea; el endpoint regex-valida primero)."""
        y, m = int(period[:4]), int(period[5:7])
        end = date(y, m, 25)
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        return date(py, pm, 26), end

    def get_commissions(
        self,
        date_from: date,
        date_to: date,
        id_seller: Optional[int] = None,           # filtro post-atribucion (HSpec §4)
        id_line: Optional[int] = None,             # corte por linea con prorrata (A-5/D-7)
        business_period: Optional[str] = None,     # etiqueta "YYYY-MM" para eco (D-5)
    ) -> Dict[str, Any]:
        """Build the cash-basis commission settlement (Pilar 3).

        Pure read-only aggregation layer (BR-49): no add/flush/commit/delete
        anywhere in this method. Queries Q1-Q5 per spec §5.3; assembly per
        §5.4: attribution chain D-2 (BR-43, first hit stops, never
        id_seller_origin, never users.active BR-51), net base D-1 (BR-42),
        proration D-7 (BR-46, LEFT OUTER JOINs => no lost weight), rate
        resolution BR-45 (line first, global fallback, lowest id wins,
        none => 0.0 + grouped warning never an HTTP error), rounding BR-48
        (2 dec PER TRAMO, sums over already-rounded values) and determinism
        BR-52. Post-attribution filters (BR-54): id_seller prunes after the
        unattributed disclosure (BR-44, always global), id_line prunes tramos
        and excludes rows without participation with a counted warning.
        """
        tax_factor = 1.0 + TAX_RATE                 # D-1
        warnings: List[str] = []

        # ── Q1: recaudos crudos de la ventana (BR-41; fila = renglon) ──────
        cash_rows = (self.db.query(
                PaymentLedgerModel.id_payment_ledger,
                PaymentLedgerModel.receipt_number,
                PaymentLedgerModel.payment_date,
                PaymentLedgerModel.payment_amount,
                PaymentLedgerModel.id_invoice,
                PaymentLedgerModel.id_customer)
             .filter(PaymentLedgerModel.transaction_nature == "CASH",
                     PaymentLedgerModel.cash_flow == "in",   # jamas 'out' ni NULL (BR-41)
                     PaymentLedgerModel.payment_date >= date_from,
                     PaymentLedgerModel.payment_date <= date_to)
             .order_by(PaymentLedgerModel.payment_date,
                       PaymentLedgerModel.id_payment_ledger)  # determinismo BR-52
             .all())

        # ── Q2: cadena factura->pedido->trip en lote (D-2 pasos 1-2). LEFT
        #        JOIN: factura sin pedido conserva su numero y la cadena rota
        #        cae al paso 3/4 (§5.3: "segunda consulta ligera o LEFT JOIN") ─
        inv_ids = sorted({r.id_invoice for r in cash_rows if r.id_invoice})
        invoice_chain: Dict[int, tuple] = {}   # id -> (invoice_number, id_seller, id_customer_trip)
        if inv_ids:
            rows = (self.db.query(
                        InvoiceModel.id_invoice, InvoiceModel.invoice_number,
                        OrderModel.id_seller, OrderModel.id_customer_trip)
                    .outerjoin(OrderModel, InvoiceModel.id_order == OrderModel.id_order)
                    .filter(InvoiceModel.id_invoice.in_(inv_ids)).all())
            invoice_chain = {r.id_invoice: (r.invoice_number, r.id_seller, r.id_customer_trip)
                             for r in rows}

        # ── Q3: customers.id_seller para trips y clientes del ledger (lote) ─
        trip_ids = {c[2] for c in invoice_chain.values() if c[2] is not None}
        trip_customer: Dict[int, int] = {}
        if trip_ids:
            trip_customer = dict(self.db.query(
                CustomerTripModel.id_customer_trip, CustomerTripModel.id_customer)
                .filter(CustomerTripModel.id_customer_trip.in_(trip_ids),
                        CustomerTripModel.id_customer.isnot(None)).all())
        cust_ids = set(trip_customer.values()) | {
            r.id_customer for r in cash_rows if r.id_customer}
        customer_seller: Dict[int, int] = {}
        if cust_ids:
            customer_seller = dict(self.db.query(
                CustomerModel.id_customer, CustomerModel.id_seller)
                .filter(CustomerModel.id_customer.in_(cust_ids),
                        CustomerModel.id_seller.isnot(None)).all())

        # ── Q4: detalles con linea por factura (D-7; mapeo identico a
        #        get_pnl reference->brand->line). LEFT OUTER JOINs: el tramo
        #        sin referencia/linea mapeada conserva id_line=NULL y cae al
        #        balde "sin linea" (tasa global) SIN peso perdido (BR-46) ────
        q4_map: Dict[int, List[tuple]] = {}   # id_invoice -> [(id_line, line_name, weight)]
        if inv_ids:
            detail_rows = (self.db.query(
                    InvoiceDetailModel.id_invoice,
                    LineModel.id_line, LineModel.line_name,
                    func.coalesce(func.sum(InvoiceDetailModel.value_without_tax), 0.0))
                 .join(InvoiceModel, InvoiceDetailModel.id_invoice == InvoiceModel.id_invoice)
                 .outerjoin(ReferenceModel,
                            InvoiceDetailModel.id_reference == ReferenceModel.id_reference)
                 .outerjoin(BrandModel, ReferenceModel.id_brand == BrandModel.id_brand)
                 .outerjoin(LineModel, BrandModel.id_line == LineModel.id_line)
                 .filter(InvoiceDetailModel.id_invoice.in_(inv_ids))
                 .group_by(InvoiceDetailModel.id_invoice, LineModel.id_line,
                           LineModel.line_name)
                 .all())
            for d in detail_rows:
                q4_map.setdefault(d.id_invoice, []).append(
                    (d.id_line, d.line_name, float(d[3])))
        for buckets in q4_map.values():
            # orden determinista de tramos (BR-52): lineas por id, luego el
            # balde sin-linea; los pesos suman el total de la factura
            buckets.sort(key=lambda b: (1 if b[0] is None else 0,
                                        b[0] if b[0] is not None else 0))

        # ── Q5: tasas activas (maestro: carga total; BR-45 resuelve contra
        #        payment_date; menor id_commission_rate gana el desempate) ────
        rates = (self.db.query(CommissionRateModel)
                 .filter(CommissionRateModel.is_active.is_(True))
                 .order_by(CommissionRateModel.id_commission_rate)
                 .all())
        line_groups: Dict[int, List[Any]] = {}
        global_group: List[Any] = []
        for r in rates:
            if r.id_line is None:
                global_group.append(r)
            else:
                line_groups.setdefault(r.id_line, []).append(r)

        # divulgaciones agrupadas (ordenes fijas al final, §6.1.3)
        missing_groups: Dict[tuple, list] = {}   # (line_id, name) -> tramo count
        tie_groups: Dict[tuple, list] = {}       # (group, ids) -> [n, chosen, min, max, name]

        def _bucket_label(line_id: Optional[int], line_name: Optional[str]) -> str:
            if line_id is None:
                return "the global (no-line) bucket"
            name = f" {line_name}" if line_name else ""
            return f"line{name} (id {line_id})"

        def _sort_key(line_id: Optional[int]) -> tuple:
            return (1 if line_id is None else 0, line_id if line_id is not None else 0)

        def _rate_for(bucket_line: Optional[int], bucket_name: Optional[str],
                      pay_date: date):
            """BR-45: tasa de la linea del tramo primero, luego global
            (id_line IS NULL). Entre vigentes multiples del mismo grupo gana
            el menor id (Q5 ya viene ordenado) + desempate divulgado."""
            for gid in ([bucket_line, None] if bucket_line is not None else [None]):
                group = global_group if gid is None else line_groups.get(gid, [])
                covering = [r for r in group if r.date_from <= pay_date <= r.date_to]
                if covering:
                    if len(covering) > 1:
                        key = _sort_key(gid) + (
                            tuple(r.id_commission_rate for r in covering),)
                        rec = tie_groups.setdefault(
                            key, [0, covering[0].id_commission_rate,
                                  pay_date, pay_date, gid,
                                  bucket_name if gid == bucket_line else None])
                        rec[0] += 1
                        rec[2] = min(rec[2], pay_date)
                        rec[3] = max(rec[3], pay_date)
                    return covering[0]
            return None

        # ── Ensamblado §5.4: atribucion -> base neta -> prorrata -> tasas ───
        unattributed_gross = 0.0
        unattributed_count = 0
        cut_count = 0
        seller_rows: Dict[int, List[Dict[str, Any]]] = {}

        for r in cash_rows:                            # Q1 ya ordenada
            gross = abs(float(r.payment_amount))       # D-6: SIEMPRE positivo
            net_base = gross / tax_factor              # D-1 (precision completa)

            # BR-43: cadena D-2 con parada al primer hit (users.active NO
            # filtra: deuda de pago persiste, BR-51)
            seller: Optional[int] = None
            chain = invoice_chain.get(r.id_invoice) if r.id_invoice else None
            if chain is not None:
                if chain[1] is not None:                   # paso 1: orders.id_seller
                    seller = chain[1]
                elif chain[2] is not None:                 # paso 2: trip -> customer
                    cust = trip_customer.get(chain[2])
                    if cust is not None:
                        seller = customer_seller.get(cust)
            if seller is None and r.id_customer is not None:   # paso 3: ledger id_customer
                seller = customer_seller.get(r.id_customer)
            if seller is None:                                 # paso 4: BR-44 divulgada
                unattributed_gross += gross
                unattributed_count += 1
                continue

            # BR-46: prorrata de la base neta; factura sin detalles o sin
            # cadena => renglon completo al balde sin-linea
            buckets = q4_map.get(r.id_invoice) if r.id_invoice else None
            total_weight = sum(b[2] for b in buckets) if buckets else 0.0
            if buckets and total_weight > 0:
                shares = [(line, name, net_base * weight / total_weight)
                          for line, name, weight in buckets]
            else:
                shares = [(None, None, net_base)]

            if id_line is not None:                    # BR-54: corte post-prorrata
                shares = [s for s in shares if s[0] == id_line]
                if not shares:
                    cut_count += 1
                    continue
            row_net = sum(s[2] for s in shares)
            # eco del bruto proporcional al corte (AC-9: L1 de CMK9 => 7.140.000)
            row_collected = round(row_net * tax_factor, 2)

            traces: List[Dict[str, Any]] = []
            earned_row = 0.0
            for line_id, line_name, share_net in shares:
                rate = _rate_for(line_id, line_name, r.payment_date)
                if rate is None:
                    pct = 0.0                          # A-11: nunca HTTP error
                    mkey = _sort_key(line_id) + (line_name,)
                    g = missing_groups.setdefault(mkey, [line_id, line_name, 0])
                    g[2] += 1
                else:
                    pct = float(rate.commission_pct)
                earned_line = round(share_net * pct / 100, 2)   # BR-48: round POR TRAMO
                earned_row += earned_line
                traces.append({
                    "id_commission_rate": rate.id_commission_rate if rate else None,
                    "id_line": line_id,
                    "line_name": line_name,
                    "commission_pct": pct,
                    "base_net": round(share_net, 2),
                    "commission_earned": earned_line,
                })
            earned_row = round(earned_row, 2)          # Σ tramos redondos

            # BR-47: tasa unica si un tramo; si no, blend efectivo conciliable
            if len(traces) == 1:
                applied = traces[0]["commission_pct"]
            else:
                applied = (round(earned_row / row_net * 100, 2) if row_net > 0 else 0.0)

            if id_seller is not None and seller != id_seller:   # post-filtro (BR-54)
                continue
            seller_rows.setdefault(seller, []).append({
                "id_payment_ledger": r.id_payment_ledger,
                "receipt_number": r.receipt_number,
                "payment_date": r.payment_date,
                "invoice_number": chain[0] if chain else None,
                "collected_amount": row_collected,
                "commission_base": round(row_net, 2),
                "commission_rate_applied": applied,
                "rate_details": traces,
                "commission_earned": earned_row,
            })

        # ── Nombres de vendedor: users solo aporta FIRST + LAST (D-2) ──────
        seller_names: Dict[int, str] = {}
        if seller_rows:
            name_rows = (self.db.query(
                UserModel.id_user, UserModel.first_name, UserModel.last_name)
                .filter(UserModel.id_user.in_(set(seller_rows))).all())
            seller_names = {n.id_user: f"{n.first_name} {n.last_name}"
                            for n in name_rows}

        # ── Bloques por vendedor (id_seller ASC, BR-52) + totales BR-48 ────
        total_collected_base = 0.0
        total_net_base = 0.0
        total_commissions = 0.0
        blocks: List[Dict[str, Any]] = []
        for sid in sorted(seller_rows):
            rows = seller_rows[sid]
            block_collected = round(sum(r["collected_amount"] for r in rows), 2)
            block_net = round(sum(r["commission_base"] for r in rows), 2)
            block_commission = round(sum(r["commission_earned"] for r in rows), 2)
            total_collected_base = round(total_collected_base + block_collected, 2)
            total_net_base = round(total_net_base + block_net, 2)
            total_commissions = round(total_commissions + block_commission, 2)
            blocks.append({
                "id_seller": sid,
                "seller_name": seller_names.get(sid, ""),
                "total_collected": block_collected,
                "total_commission": block_commission,
                "details": rows,
            })

        # ── Warnings en orden fijo §6.1.3: no-atribuibles -> tasas faltantes
        #        (agrupadas) -> exclusiones del corte id_line -> desempates ──
        if unattributed_count:
            warnings.append(
                f"{unattributed_count} unattributed collection(s) totaling "
                f"{round(unattributed_gross, 2):.2f} excluded from the settlement"
            )
        for mkey in sorted(missing_groups):
            line_id, line_name, n_tramos = missing_groups[mkey]
            warnings.append(
                f"No active commission rate for {_bucket_label(line_id, line_name)}; "
                f"{n_tramos} tramo(s) settled at 0.00"
            )
        if id_line is not None and cut_count:
            warnings.append(
                f"{cut_count} collected row(s) had no participation in line "
                f"{id_line} and were excluded from the settlement"
            )
        for tkey in sorted(tie_groups):
            n_tramos, chosen, d_min, d_max, gid, gname = tie_groups[tkey]
            warnings.append(
                f"Multiple active commission rates for {_bucket_label(gid, gname)} "
                f"overlap at payment dates {d_min.isoformat()}.."
                f"{d_max.isoformat()}; using the lowest id_commission_rate="
                f"{chosen} ({n_tramos} tramo(s) affected)"
            )

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": {
                "total_collected_base": total_collected_base,
                "total_net_base": total_net_base,
                "total_commissions_calculated": total_commissions,
                "total_unattributed_collected": round(unattributed_gross, 2),
                "unattributed_count": unattributed_count,
            },
            "commissions_by_seller": blocks,
            "meta": {
                "business_period": business_period,
                "period_source": "period_param" if business_period is not None
                                 else "explicit_dates",
                "tax_rate_used": TAX_RATE,
                "filters": {
                    "period": business_period,
                    # eco de los 5 params efectivos (BR-52): con period las
                    # fechas derivadas no se ecoan (llegaron null al endpoint)
                    "date_from": None if business_period is not None
                                 else date_from.isoformat(),
                    "date_to": None if business_period is not None
                               else date_to.isoformat(),
                    "id_seller": id_seller,
                    "id_line": id_line,
                },
                "warnings": warnings,
            },
        }
