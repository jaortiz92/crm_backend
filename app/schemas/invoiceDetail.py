# Python
from datetime import date, datetime
from typing import Optional, List, Dict, Literal

# Pydantic
from pydantic import BaseModel, Field

class InvoiceDetailBase(BaseModel):
    invoice_id: int = Field(...,
        gt=0,
        description='ID of the invoice'
    )
    product: str = Field(...,
        max_length=50,
        description='Product name (max 50 characters)'
    )
    color: str = Field(...,
        max_length=50,
        description='Color of the product (max 50 characters)'
    )
    size: str = Field(...,
        max_length=50,
        description='Size of the product (max 50 characters)'
    )
    brand_id: int = Field(...,
        gt=0,
        description='ID of the brand'
    )
    gender: Literal['M', 'F', 'U'] = Field(...,
        description='Gender (M, F, U)'
    )
    unit_value: float = Field(...,
        description='Unit value'
    )
    quantity: int = Field(...,
        description='Quantity'
    )
    value_without_tax: float = Field(...,
        description='Value without tax'
    )
    discount: float = Field(...,
        description='Discount'
    )
    value_with_tax: float = Field(...,
        description='Value with tax'
    )

class InvoiceDetailCreate(InvoiceDetailBase):
    pass

class InvoiceDetail(InvoiceDetailBase):
    id_invoice_detail: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
