# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .line import LineBase

class BrandBase(BaseModel):
    id_line: int = Field(...,
        gt=0,
        description='ID of the line associated with the brand'
    )
    brand_name: str = Field(...,
        max_length=100,
        description='Brand name (max 100 characters)'
    )

class BrandCreate(BrandBase):
    pass

class Brand(BrandBase):
    id_brand: int = Field(...,
        gt=0
    )

    class Config:
        from_attributes = True

class BrandFull(BrandBase):
    line: LineBase