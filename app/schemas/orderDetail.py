# Python
from datetime import date, datetime
from typing import Optional, List, Dict, Literal

# Pydantic
from pydantic import BaseModel, Field

# App
from app.core import Gender
from .order import OrderBase, OrderFull
from .brand import BrandFull


class OrderDetailBase(BaseModel):
    id_order: int = Field(
        ...,
        gt=0,
        description='ID of the order'
    )
    product: str = Field(
        ...,
        max_length=50,
        description='Product name (max 50 characters)'
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
    value_with_tax: float = Field(
        ...,
        description='Value with tax'
    )


class OrderDetailCreate(OrderDetailBase):
    pass


class OrderDetail(OrderDetailBase):
    id_order_detail: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class OrderDetailWithBrand(OrderDetailBase):
    brand: BrandFull


class OrderDetailFull(OrderDetailWithBrand):
    order: OrderBase


class OrderWithDetail(OrderFull):
    order_details: List[OrderDetailWithBrand]
