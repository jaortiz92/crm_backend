"""
PaymentLedger Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PaymentLedgerBase(BaseModel):
    id_account_receivable: int = Field(..., gt=0, description="FK to account receivable")
    payment_date: date = Field(..., description="Date of payment")
    payment_amount: float = Field(..., ge=0, description="Payment amount")
    payment_method: Optional[str] = Field(None, max_length=40, description="Payment method")
    reference_number: Optional[str] = Field(None, max_length=60, description="Reference number")
    id_invoice: Optional[int] = Field(None, gt=0, description="FK to CRM invoice")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class PaymentLedgerCreate(PaymentLedgerBase):
    pass


class PaymentLedger(PaymentLedgerBase):
    id_payment_ledger: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
