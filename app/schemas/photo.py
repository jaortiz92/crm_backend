# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field


class PhotoBase(BaseModel):
    id_customer: int = Field(
        ...,
        gt=0,
        description='ID of the customer the contact belongs to'
    )
    url_photo: str = Field(
        ...,
        max_length=1000,
        description='Photo link (max 1000 characters)'
    )


class PhotoCreate(PhotoBase):
    pass


class Photo(PhotoBase):
    id_photo: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
