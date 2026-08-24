"""
ActualExpense Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActualExpenseBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    expense_date: date = Field(..., description="Date of the expense")
    expense_type: str = Field(..., max_length=60, description="Category of expense")
    description: Optional[str] = Field(None, description="Detail of the expense")
    amount: float = Field(..., ge=0, description="Expense amount")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class ActualExpenseCreate(ActualExpenseBase):
    pass


class ActualExpense(ActualExpenseBase):
    id_actual_expense: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
