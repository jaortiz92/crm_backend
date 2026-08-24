"""
PayableLedger Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PayableLedgerBase(BaseModel):
    id_account_payable: int = Field(..., gt=0, description="FK to account payable")
    payment_date: date = Field(..., description="Date of payment disbursement")
    amount_paid: float = Field(..., ge=0, description="Amount paid")
    payment_reference: Optional[str] = Field(
        None, max_length=60,
        description="Payment reference (e.g. SWIFT transfer number)"
    )


class PayableLedgerCreate(PayableLedgerBase):
    pass


class PayableLedger(PayableLedgerBase):
    id_payable_ledger: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
