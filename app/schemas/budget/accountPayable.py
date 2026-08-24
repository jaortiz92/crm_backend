"""
AccountPayable Schemas
"""

from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from .payableLedger import PayableLedger


class AccountPayableBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    supplier_name: str = Field(..., max_length=120, description="Supplier name")
    total_amount: float = Field(..., ge=0, description="Total obligation amount")
    balance: Optional[float] = Field(None, ge=0, description="Outstanding balance")
    due_date: date = Field(..., description="Payment deadline")
    status: Optional[str] = Field(
        "open",
        description="Status: open, partial, paid"
    )


class AccountPayableCreate(AccountPayableBase):
    pass


class AccountPayable(AccountPayableBase):
    id_account_payable: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountPayableFull(AccountPayable):
    ledger_entries: List[PayableLedger] = []
