"""
BudgetLine Schemas
"""

import enum
from typing import Optional

from pydantic import BaseModel, Field

from .costCenter import CostCenter


class LineTypeEnum(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class BudgetLineBase(BaseModel):
    id_budget: int = Field(..., gt=0, description="FK to budget")
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    line_type: LineTypeEnum = Field(
        ...,
        description="Line type: income, expense"
    )
    month: int = Field(..., ge=1, le=12, description="Month (1-12)")
    projected_amount: float = Field(..., ge=0, description="Projected amount")
    description: Optional[str] = Field(None, description="Optional description")


class BudgetLineCreate(BudgetLineBase):
    pass


class BudgetLine(BudgetLineBase):
    id_budget_line: int = Field(..., gt=0)

    class Config:
        from_attributes = True


class BudgetLineFull(BudgetLine):
    cost_center: Optional[CostCenter] = None
