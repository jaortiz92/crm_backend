# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .customer import CustomerBase
from .brand import Brand


class CustomerBrandBase(BaseModel):
    id_customer: int = Field(
        ...,
        gt=0,
        description='ID of the customer associated with the brand'
    )
    id_brand: int = Field(
        ...,
        gt=0,
        description='ID of the brand associated with the customer'
    )


class CustomerBrandCreate(CustomerBrandBase):
    pass


class CustomerBrand(CustomerBrandBase):
    id_customer_brand: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
