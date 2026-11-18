"""
PaymentLedger Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PaymentLedgerBase(BaseModel):
    receipt_number: str = Field(
        ..., max_length=60, pattern="^[0-9A-Za-z]+$",
        description="Cleaned receipt number, alphanumeric only, e.g. 'RC3017'",
    )
    transaction_nature: str = Field(
        ..., pattern="^(CASH|NON_CASH_ADJUSTMENT)$",
        description="CASH for RC/CE; NON_CASH_ADJUSTMENT for NC/NO/DMC/SI",
    )
    cash_flow: Optional[str] = Field(
        None, pattern="^(in|out)$", description="Direction; only for CASH rows"
    )
    payment_date: date = Field(..., description="Exact collection/payment date")
    payment_amount: float = Field(
        ...,
        description="Signed bank-view amount: positive inflow, negative outflow",
    )
    accounting_account: str = Field(
        ..., max_length=20, description="Account code before the first space"
    )
    description: Optional[str] = Field(
        None, description="Full Concepto text from Excel"
    )
    third_party: Optional[str] = Field(
        None, max_length=200, description="Customer or supplier free text"
    )
    id_account_receivable: Optional[int] = Field(None, gt=0)
    id_customer: Optional[int] = Field(None, gt=0)
    id_invoice: Optional[int] = Field(
        None, gt=0, description="Affected invoice imputed from Concepto"
    )
    payment_method: Optional[str] = Field(None, max_length=40, description="Payment method")
    reference_number: Optional[str] = Field(None, max_length=60, description="Reference number")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class PaymentLedgerCreate(PaymentLedgerBase):
    pass


class PaymentLedger(PaymentLedgerBase):
    id_payment_ledger: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
