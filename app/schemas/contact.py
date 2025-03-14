# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field, EmailStr

# App
from app.core import Gender
from .customer import CustomerBase
from .role import RoleBase
from .city import CityFull


class ContactBase(BaseModel):
    id_customer: int = Field(
        ...,
        gt=0,
        description='ID of the customer the contact belongs to'
    )
    first_name: str = Field(
        ...,
        max_length=100,
        description='first name (max 100 characters)'
    )
    last_name: str = Field(
        ...,
        max_length=100,
        description='last name (max 100 characters)'
    )
    document: float = Field(
        ...,
        description='document number'
    )
    gender: Gender = Field(
        ...,
        description='gender'
    )
    email: Optional[EmailStr] = Field(
        None,
        description='email address'
    )
    phone: Optional[str] = Field(
        None,
        max_length=20,
        description='phone number (max 20 characters)'
    )
    id_role: int = Field(
        ...,
        gt=0,
        description='ID of the role assigned to the contact'
    )
    birth_date: Optional[date] = Field(
        None,
        description='birth date'
    )
    id_city: int = Field(
        ...,
        gt=0,
        description='ID of the city the Customer resides in'
    )
    relevant_details: Optional[str] = Field(
        ...,
        max_length=1000,
        description='Relevant details (max 1000 characters)'
    )
    active: bool = Field(
        ...,
        description='Indicates whether the user is active or not'
    )


class ContactCreate(ContactBase):
    pass


class Contact(ContactBase):
    id_contact: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class ContactFull(Contact):
    customer: Optional[CustomerBase]
    role: Optional[RoleBase]
    city: Optional[CityFull]
