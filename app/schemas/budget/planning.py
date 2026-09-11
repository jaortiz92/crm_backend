"""
Planning Schemas (BE-S4-BUDGET-PLANNING)

Request/response models for the /budget/planning sub-router
(spec backend.02_12 §5). No new tables or columns: everything maps to the
existing budgets / budget_lines model surface.
"""

import math
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .budget import BudgetFull


class PlanningUploadResult(BaseModel):
    """Response 201 for POST /budget/planning/upload (spec §5.1)."""

    id_budget: int
    scenario_name: str
    budget_year: int
    lines_income: int
    lines_expense: int
    # Sum of projected_amount over income budget_lines created.
    total_income: float
    # Sum of projected_amount over expense budget_lines created; variable
    # rows contribute 0 (their amount lives in variable_rate).
    total_expense_fixed: float
    # Extra lines produced by line_payment_rules expansion:
    # lines_income - processed_excel_income_rows (BR-ING-05).
    payment_rules_expansions: int


class PlanningCloneRequest(BaseModel):
    """Request body for POST /budget/planning/clone (spec §5.2)."""

    id_budget: int = Field(..., gt=0, description="Source budget to clone")
    nuevo_nombre: str = Field(
        ..., min_length=1, max_length=120,
        description="Name of the new scenario",
    )
    # BR-CLN-02: multiplicative factor (1 + modifier_pct/100) applied to
    # projected_amount only. Range [-100, +inf): -101 -> 422 (AC-CL-3).
    modifier_pct: float = Field(
        0.0, ge=-100.0,
        description="Percentage adjustment over projected amounts (default 0)",
    )


class PlanningCellUpdate(BaseModel):
    """Request body for PUT /budget/planning/cell/{id_budget_line} (§5.3).

    BR-CEL-01: projected_amount (and optionally description) are the ONLY
    mutable fields through this endpoint. BR-CEL-02 / ASM-12: numeric,
    finite and >= 0 (T-06); anything else -> 422.
    """

    projected_amount: float = Field(
        ..., ge=0, description="New projected amount (>= 0, finite)"
    )
    description: Optional[str] = Field(
        None, description="Optional new description (omitted = keep current)"
    )

    @field_validator("projected_amount")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        # ge=0 already rejects NaN (NaN >= 0 is False) and negatives;
        # this closes the +inf hole (T-06: finite values only).
        if not math.isfinite(v):
            raise ValueError("projected_amount must be a finite number")
        return v


class PlanningScenarioRow(BaseModel):
    """One aggregated row of GET /budget/planning/ (spec §5.4, NFR-5).

    Aggregation (lines_count / totals) happens in SQL in the CRUD layer;
    this schema is just its transport shape.
    """

    id_budget: int
    budget_name: str
    budget_year: int
    is_scenario: bool
    parent_budget_name: Optional[str] = None
    status: Optional[str] = None
    lines_count: int
    total_income: float
    total_expense: float
    created_at: Optional[datetime] = None


class PlanningSetTargetResult(BaseModel):
    """Response 200 for PUT /budget/planning/{id_budget}/set-target (§5.6)."""

    id_budget: int
    budget_year: int
    demoted_budget_id: Optional[int] = None


class PlanningDetail(BudgetFull):
    """GET /budget/planning/{id_budget}/detail (§5.5).

    Wrapper of BudgetFull (budget + budget_lines) plus the parent scenario
    name for the Grid Editor breadcrumb.
    """

    parent_budget_name: Optional[str] = None
