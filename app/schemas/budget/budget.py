"""
Budget Schemas

Includes analytical / aggregation response schemas at the bottom.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field

from .budgetLine import BudgetLine


class BudgetBase(BaseModel):
    budget_name: str = Field(..., max_length=120, description="Name of the budget")
    budget_year: int = Field(..., description="Fiscal year")
    budget_period: str = Field(
        ..., max_length=20,
        description="Period type: annual, quarterly, monthly"
    )
    id_department: Optional[int] = Field(None, gt=0, description="FK to department")
    status: Optional[str] = Field(
        "draft",
        description="Budget status: draft, active, archived"
    )
    is_scenario: Optional[bool] = Field(
        False,
        description="Whether this budget is a what-if scenario clone"
    )
    parent_budget_id: Optional[int] = Field(
        None, gt=0,
        description="FK to parent budget (for scenario clones)"
    )


class BudgetCreate(BudgetBase):
    pass


class Budget(BudgetBase):
    id_budget: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BudgetFull(Budget):
    budget_lines: List[BudgetLine] = []


# ──────────────────────────────────────────────
# Analytical / Aggregation Response Schemas
# ──────────────────────────────────────────────

class BudgetVsActual(BaseModel):
    """Response schema for budget vs actual comparison."""
    id_cost_center: int
    cost_center_code: str
    cost_center_name: str
    budget_month: int
    budgeted_amount: float
    actual_amount: float
    variance: float
    variance_percentage: Optional[float] = None


class CashFlowProjection(BaseModel):
    """Response schema for cash flow projection."""
    payment_month: int
    expected_inflows: float
    expected_outflows: float
    net_cash_flow: float
    cumulative_cash_flow: float


class BudgetTrackingSummary(BaseModel):
    """Response schema for budget tracking aggregation."""
    id_budget: int
    budget_name: str
    total_budgeted: float
    total_actual: float
    total_variance: float
    execution_percentage: Optional[float] = None
    by_month: List[BudgetVsActual] = []


# ──────────────────────────────────────────────
# P&L (Pilar 1) Response Schemas  — spec 02_09 §4.3.2
# ──────────────────────────────────────────────

class PnLComparison(BaseModel):
    actual: Optional[float] = None      # Optional: en modo corte hay lineas no filtrables (null)
    budget: Optional[float] = None      # None = sin presupuesto aplicable / no cortable
    variance: Optional[float] = None    # convencion de favorabilidad (D-4)
    variance_pct: Optional[float] = None


class PnLProfit(BaseModel):
    actual: Optional[float] = None
    budget: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    margin_pct: Optional[float] = None          # real (A-9)
    margin_pct_budget: Optional[float] = None   # presupuestado (aditivo, no rompe el contrato del HSpec)


class OpexBreakdownItem(BaseModel):
    category: str        # expense_type del libro auxiliar
    actual: float


class PnLOpex(PnLComparison):
    breakdown: Optional[List[OpexBreakdownItem]] = None   # solo con include_breakdown=true


class PnLStatement(BaseModel):
    revenues: PnLComparison
    cogs: PnLComparison
    gross_profit: PnLProfit
    opex: PnLOpex
    operating_profit: PnLProfit


class CogsBudgetTraceItem(BaseModel):
    id_cost_center: int
    cost_center_code: Optional[str] = None       # denormalizado para tooltips de UI
    id_line: Optional[int] = None                # linea del CECO (null = sin linea)
    pct: float                                   # tasa aplicada (0-100)
    source: str                                  # "line" | "global" (D-6)
    income_budget: float                         # ingreso presupuestado del CECO en el periodo
    cogs_contribution: float                     # income_budget * pct / 100 (2 dec)


class PnLMeta(BaseModel):
    mode: str                                    # "consolidated" | "slice"
    budget_source: Optional[dict] = None         # {id_budget, budget_name, status}
    filters: dict                                # eco exacto de los query params recibidos
    not_filterable: List[str] = []               # p.ej. "revenues (no cost-center dimension)"
    cogs_budget_trace: List[CogsBudgetTraceItem] = []   # D-6: auditoria CECO-por-CECO de cogs.budget
    warnings: List[str] = []                     # BR-15: tasas faltantes, ano cruzado, NC sin referencia


class PnLResponse(BaseModel):
    period: dict          # {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}  — mismo shape que el HSpec
    pnl_statement: PnLStatement
    meta: PnLMeta


# ──────────────────────────────────────────────
# Cash Flow (Pilar 2) Response Schemas  — spec 02_10 §4.3
# ──────────────────────────────────────────────

class CashFlowPoint(BaseModel):
    period: str                        # label ISO del bucket (BR-34; puede ser anterior a
                                       # date_from en el primer bucket semanal parcial)
    status: str                        # "actual" | "projected" (D-3/BR-24)
    inflows: float                     # >= 0
    outflows: float                    # <= 0 (convencion del JSON de ejemplo del HSpec)
    net_flow: float                    # = inflows + outflows (nunca se "resta el negativo")
    accumulated_balance: float         # running-sum desde starting_balance (BR-35)


class CashFlowSummary(BaseModel):
    starting_balance: float
    ending_balance: float              # = starting + SUM(net_flow)  (invariante BR-35)
    net_flow: float                    # suma de net_flow de toda la ventana


class CashFlowMeta(BaseModel):
    granularity: str
    cutoff: str                        # fecha del punto de inflexion realmente usada (BR-37)
    initial_balance_source: str        # "provided" | "derived_from_ledger" (D-4)
    outflow_source: str                # eco efectivo (D-1)
    overdue_as: str                    # eco efectivo (D-2)
    budget_source: Optional[dict] = None   # {id_budget, budget_name, status} | null (D-7)
    overdue_outflows: float = 0.0      # total AP clampado/excluido segun modo
    filters: dict                      # eco de los query params efectivos (BR-39)
    warnings: List[str] = []


class CashFlowResponse(BaseModel):
    summary: CashFlowSummary
    time_series: List[CashFlowPoint]
    meta: CashFlowMeta
