# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field, validator


class ActivityTypeBase(BaseModel):
    activity: str = Field(
        ...,
        max_length=100,
        description='Activity name (max 100 characters)'
    )
    mandatory: bool = Field(
        ...,
        description='Whether the activity is mandatory'
    )
    category: str = Field(
        ...,
        max_length=30,
        description='Category name (max 30 characters)'
    )
    activity_order: int = Field(
        0,
        description='Order of the activity (0 for non-mandatory)'
    )

    @validator('activity_order')
    def validate_activity_order(cls, v, values):
        mandatory = values.get('mandatory')
        if mandatory and v < 1:
            raise ValueError('Mandatory activities must have activity_order >= 1')
        if not mandatory and v != 0:
            raise ValueError('Non-mandatory activities must have activity_order = 0')
        return v


class ActivityTypeReorder(BaseModel):
    id_activity_type: int = Field(..., gt=0)
    activity_order: int = Field(..., gt=0)


class ActivityTypeBatchReorder(BaseModel):
    activities: list[ActivityTypeReorder] = Field(..., min_length=1)


class ActivityTypeCreate(ActivityTypeBase):
    pass


class ActivityType(ActivityTypeBase):
    id_activity_type: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True
