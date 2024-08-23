# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

# App
from core import Gender

class UserBase(BaseModel):
    username: str = Field(...,
        max_length=100,
        description='Unique username (max 100 characters)'
    )
    password: str = Field(...,
        max_length=500, 
        description='Password hash (max 500 characters)'
    )
    first_name: str = Field(...,
        max_length=100,
        description='First name (max 100 characters)'
    )
    last_name: str = Field(...,
        max_length=100,
        description='Last name (max 100 characters)'
    )
    document: float = Field(...,
        description='Document number'
    )
    gender: Gender = Field(...,
        description='gender'
    )
    role_id: int = Field(...,
        gt=0,
        description='ID of the role assigned to the user'
    )
    email: EmailStr = Field(...,
        description='Email address'
    )
    phone: Optional[str] = Field(None,
        max_length=20,
        description='Phone number (max 20 characters)'
    )
    city_id: int = Field(...,
        gt=0,
        description='ID of the city the user resides in'
    )
    birth_date: Optional[date] = Field(None,
        description='Users birth date'
    )
    active: bool = Field(...,
        description='Indicates whether the user is active or not'
    )
    

class UserCreate(UserBase):
    pass

class User(UserBase):
    id_user: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
