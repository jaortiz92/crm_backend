# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field, EmailStr

# App
from .storeType import StoreTypeBase
from .originType import OriginTypeBase
from .brand import BrandFull
from .user import UserBase
from .city import CityFull


class CustomerBase(BaseModel):
    company_name: str = Field(
        ...,
        max_length=100,
        description='Business name (max 100 characters)'
    )
    document: float = Field(
        ...,
        description='document number'
    )


class CustomerBaseCreate(CustomerBase):
    email: Optional[EmailStr] = Field(
        ...,
        description='email address'
    )
    phone: Optional[str] = Field(
        None,
        max_length=20,
        description='phone number (max 20 characters)'
    )
    id_origin_type: Optional[int] = Field(
        ...,
        gt=0,
        description='ID of the origin type associated with the Customer'
    )
    date_started_buying: Optional[date] = Field(
        ...,
        description='Date on which the customer started buying'
    )
    id_store_type: Optional[int] = Field(
        ...,
        gt=0,
        description='ID of the store type associated with the Customer'
    )
    address: Optional[str] = Field(
        ...,
        max_length=255,
        description='address (max 255 characters)'
    )
    id_seller: Optional[int] = Field(
        ...,
        gt=0,
        description='ID of the seller associated with the Customer'
    )
    stores: Optional[int] = Field(
        ...,
        gt=0,
        description='Stores associated with the Customer'
    )
    id_city: Optional[int] = Field(
        ...,
        gt=0,
        description='ID of the city the Customer resides in'
    )
    active: bool = Field(
        ...,
        description='Indicates whether the user is active or not'
    )

    credit_limit: Optional[float] = Field(
        0,
        description='Credit quota for customers'
    )

    with_documents: Optional[float] = Field(
        False,
        description='Credit quota for customers'
    )

    relevant_details: Optional[str] = Field(
        ...,
        max_length=1000,
        description='Relevant details (max 1000 characters)'
    )

    social_media: Optional[str] = Field(
        ...,
        max_length=1000,
        description='Social media (max 1000 characters)'
    )


class CustomerCreate(CustomerBaseCreate):
    brand_ids: List[int] = Field(
        ...,
        description='ID of the brands associated with the Customer'
    )


class Customer(CustomerBaseCreate):
    id_customer: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class CustomerFull(Customer):
    store_type: Optional[StoreTypeBase]
    origin_type: Optional[OriginTypeBase]
    brands: Optional[List[BrandFull]]
    seller: Optional[UserBase]
    city: Optional[CityFull]


class CustomerBaseWithCity(CustomerBase):
    city: Optional[CityFull]
