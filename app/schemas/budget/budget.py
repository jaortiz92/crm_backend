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
    month: int
    budgeted_amount: float
    actual_amount: float
    variance: float
    variance_percentage: Optional[float] = None


class CashFlowProjection(BaseModel):
    """Response schema for cash flow projection."""
    month: int
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
