# Python
from typing import Optional, List, Dict
from datetime import date

# Pydantic
from pydantic import BaseModel, EmailStr, Field


class OriginTypeBase(BaseModel):
    origin_type: str = Field(
        ...,
        max_length=100,
        description='Origin type name (max 100 characters)'
    )
    description: str = Field(
        ...,
        max_length=100,
        description='Product description (max 100 characters)'
    )


class OriginTypeCreate(OriginTypeBase):
    pass


class OriginType(OriginTypeBase):
    id_origin_type: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
