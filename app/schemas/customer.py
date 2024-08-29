# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field, EmailStr

class CustomerBase(BaseModel):
    company_name: str = Field(...,
        max_length=100,
        description='Business name (max 100 characters)'
    )
    document: float = Field(...,
        description='document number'
    )
    email: EmailStr = Field(...,
        description='email address'
    )
    phone: Optional[str] = Field(None,
        max_length=20,
        description='phone number (max 20 characters)'
    )
    id_store_type: int = Field(...,
        gt=0,
        description='ID of the store type associated with the Customer'
    )
    address: str = Field(...,
        max_length=255,
        description='address (max 255 characters)'
    )
    id_brand: int = Field(...,
        gt=0,
        description='ID of the brand associated with the Customer'
    )
    id_seller: int = Field(...,
        gt=0,
        description='ID of the seller associated with the Customer'
    )
    stores: int = Field(...,
        gt=0,
        description='Stores associated with the Customer'
    )
    id_city: int = Field(...,
        gt=0,
        description='ID of the city the Customer resides in'
    )
    active: bool = Field(...,
        description='Indicates whether the user is active or not'
    )

class CustomerCreate(CustomerBase):
    pass

class Customer(CustomerBase):
    id_customer: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
