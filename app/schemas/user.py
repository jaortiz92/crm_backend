# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

# App
from app.core import Gender
from .city import CityFull
from .role import RoleBase


class UserBase(BaseModel):
    first_name: str = Field(
        ...,
        max_length=100,
        description='First name (max 100 characters)'
    )
    last_name: str = Field(
        ...,
        max_length=100,
        description='Last name (max 100 characters)'
    )
    document: float = Field(
        ...,
        description='Document number'
    )
    gender: Gender = Field(
        ...,
        description='gender'
    )

class UserBaseOut(UserBase):
    username: str = Field(
        ...,
        max_length=100,
        description='Unique username (max 100 characters)'
    ),
    id_role: int = Field(
        ...,
        gt=0,
        description='ID of the role assigned to the user'
    )
    email: EmailStr = Field(
        ...,
        description='Email address'
    )
    phone: Optional[str] = Field(
        None,
        max_length=20,
        description='Phone number (max 20 characters)'
    )
    id_city: int = Field(
        ...,
        gt=0,
        description='ID of the city the user resides in'
    )
    birth_date: Optional[date] = Field(
        None,
        description='Users birth date'
    )
    active: bool = Field(
        ...,
        description='Indicates whether the user is active or not'
    )

class UserCreate(UserBaseOut):
    password: str = Field(
        ...,
        max_length=500,
        description='Password hash (max 500 characters)'
    )


class User(UserCreate):
    id_user: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class UserFull(UserBaseOut):
    id_user: int
    city: Optional[CityFull]
    role: Optional[RoleBase]