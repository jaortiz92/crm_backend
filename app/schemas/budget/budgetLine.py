"""
BudgetLine Schemas
"""

import enum
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .costCenter import CostCenter


class LineTypeEnum(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class BehaviorTypeEnum(str, enum.Enum):
    FIXED = "fixed"
    VARIABLE_SALES = "variable_sales"
    VARIABLE_RECEIVABLES = "variable_receivables"


class BudgetLineBase(BaseModel):
    id_budget: int = Field(..., gt=0, description="FK to budget")
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    line_type: LineTypeEnum = Field(
        ...,
        description="Line type: income, expense"
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
