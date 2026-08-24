from typing import Optional

from pydantic import BaseModel, Field


class ManagementBase(BaseModel):
    management_name: str = Field(
        ...,
        max_length=100,
        description='Management name (max 100 characters)'
    )
    management_code: Optional[str] = Field(
        None,
        max_length=10,
        description='Management code (max 10 characters)'
    )


class ManagementCreate(ManagementBase):
    pass


class Management(ManagementBase):
    id_management: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
