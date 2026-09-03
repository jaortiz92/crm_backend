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
    total_amount: float = Field(
        ..., description="Total amount (puede ser negativo: saldos a favor)"
    )
    paid_amount: Optional[float] = Field(0, description="Amount paid so far")
    balance: Optional[float] = Field(0, description="Outstanding balance")
    status: Optional[str] = Field(
        "OPEN",
        description="Status: OPEN, PARTIAL, PAID"
    )
    aging_bucket: Optional[str] = Field(
        None, max_length=20,
        description="Aging bucket: current, 30, 60, 90+"
    )
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")
    customer_document: Optional[float] = Field(
        None, description="Numeric root of customer identification from source file"
    )
    identification_original: Optional[str] = Field(
        None, max_length=50, description="Raw identification text from source file"
    )
    statement_date: Optional[date] = Field(None, description="Statement cutoff date")


class AccountReceivableCreate(AccountReceivableBase):
    pass


class AccountReceivable(AccountReceivableBase):
    id_account_receivable: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AccountReceivableFull(AccountReceivable):
    payments: List[PaymentLedger] = []
