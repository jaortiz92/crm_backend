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
    username: str = Field(
        ...,
        max_length=100,
        description='Unique username (max 100 characters)'
    ),
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


class UserCreate(UserBase):
    password: str = Field(
        ...,
        max_length=500,
        description='Password hash (max 500 characters)'
    )


class User(UserBase):
    id_user: int = Field(
        ...,
        gt=0
    )
    id_role: int = Field(
        ...,
        gt=0,
        description='ID of the role assigned to the user'
    )
    active: bool = Field(
        ...,
        description='Indicates whether the user is active or not'
    )

    class Config:
        from_attributes = True


class UserFull(User):
    id_user: int
    city: Optional[CityFull]
    role: Optional[RoleBase]


class UserPasswordUpdate(BaseModel):
    current_password: str = Field(
        ..., max_length=500,
        description="Current password"
    )
    new_password: str = Field(
        ..., max_length=500, description="New password"
    )


class UserPasswordResetRequest(BaseModel):
    email: EmailStr = Field(
        ...,
        description="User's email for password recovery"
    )


class UserPasswordReset(BaseModel):
    token: str = Field(
        ..., description="Password reset token"
    )
    new_password: str = Field(
        ..., max_length=500, description="New password"
    )
