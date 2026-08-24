from typing import Optional

from pydantic import BaseModel, Field


class AreaBase(BaseModel):
    area_name: str = Field(
        ...,
        max_length=100,
        description='Area name (max 100 characters)'
    )
    area_code: Optional[str] = Field(
        None,
        max_length=10,
        description='Area code (max 10 characters)'
    )
    id_management: Optional[int] = Field(
        None,
        gt=0,
        description='FK to management'
    )


class AreaCreate(AreaBase):
    pass


class Area(AreaBase):
    id_area: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
