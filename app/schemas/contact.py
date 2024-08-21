# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field, EmailStr

class ContactBase(BaseModel):
    client_id: int = Field(...,
        gt=0,
        description='ID of the client the contact belongs to'
    )
    first_name: str = Field(...,
        max_length=100,
        description='first name (max 100 characters)'
    )
    last_name: str = Field(...,
        max_length=100,
        description='last name (max 100 characters)'
    )
    document: float = Field(...,
        description='document number'
    )
    email: Optional[EmailStr] = Field(None,
        description='email address'
    )
    phone: Optional[str] = Field(None,
        max_length=20,
        description='phone number (max 20 characters)'
    )
    store_type_id: int = Field(...,
        gt=0,
        description='ID of the store type associated with the contact'
    )
    role_id: int = Field(...,
        gt=0,
        description='ID of the role assigned to the contact'
    )
    birth_date: Optional[date] = Field(None,
        description='birth date'
    )

class ContactCreate(ContactBase):
    pass

class Contact(ContactBase):
    id_contact: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True