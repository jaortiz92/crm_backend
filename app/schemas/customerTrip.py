# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .customer import CustomerBase
from .user import UserBase
from .collection import CollectionFull


class CustomerTripBase(BaseModel):
    id_customer: int = Field(
        ...,
        gt=0,
        description='ID of the Customer'
    )
    id_seller: int = Field(
        ...,
        gt=0,
        description='ID of the seller'
    )
    id_collection: int = Field(
        ...,
        gt=0,
        description='ID of the collection'
    )
    budget: float = Field(
        ...,
        description='Budget for the trip'
    )
    ordered: Optional[bool] = Field(
        None,
        description='Whether the Customer placed an order'
    )
    comment: Optional[str] = Field(
        None,
        description='Comments about the trip'
    )


class CustomerTripCreate(CustomerTripBase):
    pass


class CustomerTrip(CustomerTripBase):
    id_customer_trip: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class CustomerTripFull(CustomerTrip):
    customer: CustomerBase
    seller: UserBase
    collection: CollectionFull