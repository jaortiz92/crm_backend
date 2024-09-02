# Python
from typing import Optional, List, Dict
from datetime import date

# Pydantic
from pydantic import BaseModel, EmailStr, Field

class StoreTypeBase(BaseModel):
    store_type: str = Field(...,
        max_length=100,
        description='Store type name (max 100 characters)'
    )

class StoreTypeCreate(StoreTypeBase):
    pass

class StoreType(StoreTypeBase):
    id_store_type: int = Field(...,
        gt=0
    )

    class Config:
        from_attributes = True
