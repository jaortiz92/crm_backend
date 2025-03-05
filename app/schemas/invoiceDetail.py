# Python
from datetime import date, datetime
from typing import Optional, List, Dict, Literal

# Pydantic
from pydantic import BaseModel, Field

# App
from app.core import Gender
from .invoice import InvoiceBase, InvoiceFull
from .brand import BrandFull


class InvoiceDetailBase(BaseModel):
    id_invoice: int = Field(
        ...,
        gt=0,
        description='ID of the invoice'
    )
    product: str = Field(
        ...,
        max_length=50,
        description='Product name (max 50 characters)'
    )
    description: str = Field(
        ...,
        max_length=50,
        description='Product description (max 50 characters)'
    )
    color: str = Field(
        ...,
        max_length=50,
        description='Color of the product (max 50 characters)'
    )
    size: str = Field(
        ...,
        max_length=50,
        description='Size of the product (max 50 characters)'
    )
    id_brand: int = Field(
        ...,
        gt=0,
        description='ID of the brand'
    )
    gender: Gender = Field(
        ...,
        description='gender'
    )
    unit_value: float = Field(
        ...,
        description='Unit value'
    )
    quantity: int = Field(
        ...,
        description='Quantity'
    )
    value_without_tax: float = Field(
        ...,
        description='Value without tax'
    )
    discount: float = Field(
        ...,
        description='Discount'
    )
    value_with_tax: float = Field(
        ...,
        description='Value with tax'
    )


class InvoiceDetailCreate(InvoiceDetailBase):
    pass


class InvoiceDetail(InvoiceDetailBase):
    id_invoice_detail: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class InvoiceDetailWithBrand(InvoiceDetailBase):
    brand: BrandFull


class InvoiceDetailFull(InvoiceDetailWithBrand):
    invoice: InvoiceBase


class InvoiceWithDetail(InvoiceFull):
    invoice_details: List[InvoiceDetailWithBrand]


class InvoiceDetailByBrand(BaseModel):
    brand_name: str = Field(
        ...,
        max_length=100,
        description='Brand name (max 100 characters)'
    )
    gender: Gender = Field(
        ...,
        description='gender'
    )
    quantity: int = Field(
        ...,
        description='Quantity'
    )
    discount: float = Field(
        ...,
        description='Discount'
    )
    value_without_tax: float = Field(
        ...,
        description='Value without tax'
    )
    value_with_tax: float = Field(
        ...,
        description='Value with tax'
    )

    class Config:
        from_attributes = True


class InvoiceDetailByDescription(BaseModel):
    description: str = Field(
        ...,
        max_length=50,
        description='Product description (max 50 characters)'
    )
    quantity: int = Field(
        ...,
        description='Quantity'
    )
    value_without_tax: float = Field(
        ...,
        description='Value without tax'
    )

    class Config:
        from_attributes = True


class InvoiceDetailBySize(BaseModel):
    size: str = Field(
        ...,
        max_length=50,
        description='Size of the product (max 50 characters)'
    )
    quantity: int = Field(
        ...,
        description='Quantity'
    )
    value_without_tax: float = Field(
        ...,
        description='Value without tax'
    )

    class Config:
        from_attributes = True
