# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .order import OrderFull


class InvoiceBase(BaseModel):
    invoice_number: str = Field(...,
        max_length=20,
        description='Invoice number (max 20 characters)'
    )
    invoice_date: date = Field(...,
        description='Date of the invoice'
    )
    id_order: int = Field(...,
        gt=0,
        description='ID of the order'
    )


class InvoiceCreate(InvoiceBase):
    pass


class Invoice(InvoiceBase):
    id_invoice: int = Field(...,
        gt=0
    )


    class Config:
        from_attributes = True


class InvoiceShow(Invoice):
    quantity: float
    value_without_tax: float
    value_with_tax: float


class InvoiceFull(InvoiceShow):
    order: OrderFull