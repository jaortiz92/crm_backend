# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .customer import CustomerBaseWithCity
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
        description='Budget in value for the trip'
    )
    budget_quantities: int = Field(
        ...,
        description='Budget in quantities for the trip'
    )
    closed: Optional[bool] = Field(
        None,
        description='Whether the Customer Trip is closed'
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
    customer: CustomerBaseWithCity
    seller: UserBase
    collection: CollectionFull
