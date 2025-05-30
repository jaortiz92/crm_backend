# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field


class ActivityTypeBase(BaseModel):
    activity: str = Field(
        ...,
        max_length=100,
        description='Activity name (max 100 characters)'
    )
    mandatory: bool = Field(
        None,
        description='Whether the activity is mandatory'
    )
    category: str = Field(
        ...,
        max_length=30,
        description='Category name (max 30 characters)'
    )
    activity_order: int = Field(
        None,
        description='Order of the activity'
    )


class ActivityTypeCreate(ActivityTypeBase):
    pass


class ActivityType(ActivityTypeBase):
    id_activity_type: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
