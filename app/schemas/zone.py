from typing import Optional

from pydantic import BaseModel, Field


class ZoneBase(BaseModel):
    zone_name: str = Field(
        ...,
        max_length=80,
        description='Zone name (max 80 characters)'
    )
    zone_code: str = Field(
        ...,
        max_length=10,
        description='Zone code (max 10 characters)'
    )


class ZoneCreate(ZoneBase):
    pass


class Zone(ZoneBase):
    id_zone: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
