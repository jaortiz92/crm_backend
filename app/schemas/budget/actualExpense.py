"""
ActualExpense Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActualExpenseBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    accounting_account: str = Field(..., max_length=20, description="Accounting account code")
    expense_date: date = Field(..., description="Date of the expense")
    expense_type: str = Field(..., max_length=60, description="Category of expense")
    description: Optional[str] = Field(None, description="Detail of the expense")
    amount: float = Field(..., description="Expense amount (negative for credit notes)")
    document_number: str = Field(..., max_length=50, description="Document/voucher number")
    third_party_account: Optional[str] = Field(None, description="Third party account info")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class ActualExpenseCreate(ActualExpenseBase):
    pass


class ActualExpense(ActualExpenseBase):
    id_actual_expense: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
