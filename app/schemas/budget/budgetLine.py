"""
BudgetLine Schemas
"""

import enum
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .costCenter import CostCenter


class LineTypeEnum(str, enum.Enum):
    """Mirror of app/models/budget/budgetLine.py (BE-S8 §3.1): PURCHASE is
    the third member — imported merchandise whose supplier payments are
    read-derived installments (payment_date stays NULL, behavior fixed).
    Existing DBs need the manual ALTER TYPE of §3.3 before deploying."""
    INCOME = "income"
    EXPENSE = "expense"
    PURCHASE = "purchase"


class BehaviorTypeEnum(str, enum.Enum):
    FIXED = "fixed"
    VARIABLE_SALES = "variable_sales"
    VARIABLE_RECEIVABLES = "variable_receivables"


class BudgetLineBase(BaseModel):
    id_budget: int = Field(..., gt=0, description="FK to budget")
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    line_type: LineTypeEnum = Field(
        ...,
        description="Line type: income, expense, purchase (a purchase "
                    "optionally carries a season: id_collection is valid "
                    "on it per backend.02_18 A-01 §10.2)"
    )
    budget_date: date = Field(..., description="Date when the income/expense occurs (P&L)")
    payment_date: Optional[date] = Field(None, description="Date when cash flows (Cash Flow)")
    id_collection: Optional[int] = Field(None, gt=0, description="FK to collection")
    projected_amount: float = Field(..., ge=0, description="Projected amount")
    description: Optional[str] = Field(None, description="Optional description")
    behavior_type: BehaviorTypeEnum = Field(
        BehaviorTypeEnum.FIXED,
        description="Cost behavior: fixed, variable_sales, variable_receivables"
    )
    variable_rate: Optional[float] = Field(
        None,
        ge=0,
        le=1,
        description="Variable rate (0-1). Required when behavior_type is not 'fixed'"
    )
    # BE-S10-IVA (spec backend.02_20 §5.2): additive Optional[bool] on the
    # BASE so every response that serializes a line (BudgetLine /
    # BudgetLineFull / PlanningDetail) gains the key AND BudgetLineCreate
    # can round-trip the ETL flag through create_budget_lines_bulk (the
    # upload path builds dicts -> BudgetLineCreate(**data) -> model_dump).
    # None means "no explicit decision" and the DERIVATION reads NULL ≡
    # True (D-S10-3); it is never a DB default. Meaningful on EXPENSE:
    # INCOME ignores it (D-S10-5), PURCHASE is always taxed (§3.1).
    has_iva: Optional[bool] = Field(
        None,
        description="Con IVA flag (BE-S10-IVA): true/false explicit, "
                    "null = legacy/no-decision (derivation reads it as "
                    "con IVA, D-S10-3). Only meaningful for expense lines.",
    )

    @field_validator("variable_rate")
    @classmethod
    def validate_variable_rate(cls, v, info):
        behavior = info.data.get("behavior_type")
        if behavior and behavior != BehaviorTypeEnum.FIXED and v is None:
            raise ValueError("variable_rate is required when behavior_type is not 'fixed'")
        return v


class BudgetLineCreate(BudgetLineBase):
    pass


class BudgetLine(BudgetLineBase):
    id_budget_line: int = Field(..., gt=0)

    class Config:
        from_attributes = True


class BudgetLineFull(BudgetLine):
    cost_center: Optional[CostCenter] = None
