# Python
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

# App
from .line import LineBase

class CollectionBase(BaseModel):
    id_line: int = Field(...,
        gt=0,
        description='ID of the line'
    )
    collection_name: str = Field(...,
        max_length=30,
        description='Collection name (max 30 characters)'
    )
    short_collection_name: str = Field(...,
        max_length=10,
        description='Short name of the collection (max 10 characters)'
    )
    year: int = Field(...,
        description='Year of the collection',
        ge=2018
    )
    quarter: int = Field(...,
        description='Quarter of the collection',
        ge=1,
        le=4
    )

class CollectionCreate(CollectionBase):
    pass

class Collection(CollectionBase):
    id_collection: int = Field(...,
        gt=0
    )

    class Config:
        from_attributes = True


class CollectionFull(Collection):
    line: LineBase