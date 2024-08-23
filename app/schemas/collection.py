# Python
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

class CollectionBase(BaseModel):
    line_id: int = Field(...,
        gt=0,
        description='ID of the line'
    )
    collection: str = Field(...,
        max_length=30,
        description='Collection name (max 30 characters)'
    )
    short_name: str = Field(...,
        max_length=10,
        description='Short name of the collection (max 10 characters)'
    )
    year: int = Field(...,
        description='Year of the collection'
    )
    quarter: int = Field(...,
        description='Quarter of the collection'
    )

class CollectionCreate(CollectionBase):
    pass

class Collection(CollectionBase):
    id_collection: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
