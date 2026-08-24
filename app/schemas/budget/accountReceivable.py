"""
AccountReceivable Schemas
"""

from datetime import date, datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from .paymentLedger import PaymentLedger


class AccountReceivableBase(BaseModel):
    id_customer: Optional[int] = Field(None, gt=0, description="FK to CRM customer")
    id_invoice: Optional[int] = Field(None, gt=0, description="FK to CRM invoice")
    document_number: str = Field(..., max_length=50, description="Document number")
    due_date: date = Field(..., description="Due date (Fecha Vence)")
    total_amount: float = Field(..., ge=0, description="Total amount")
    paid_amount: Optional[float] = Field(0, ge=0, description="Amount paid so far")
    balance: Optional[float] = Field(0, description="Outstanding balance")
    status: Optional[str] = Field(
        "open",
        description="Status: open, partial, paid, overdue"
    )
    aging_bucket: Optional[str] = Field(
        None, max_length=20,
        description="Aging bucket: current, 30, 60, 90+"
    )
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class AccountReceivableCreate(AccountReceivableBase):
    pass


class AccountReceivable(AccountReceivableBase):
    id_account_receivable: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountReceivableFull(AccountReceivable):
    payments: List[PaymentLedger] = []
