# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .activityType import ActivityTypeBase
from .user import UserBase
from .customerTrip import CustomerTripFull


class ActivityBase(BaseModel):
    id_customer_trip: int = Field(
        ...,
        gt=0,
        description='ID of the customer trip'
    )
    id_activity_type: int = Field(
        ...,
        gt=0,
        description='ID of the activity type'
    )
    id_user: int = Field(
        ...,
        gt=0,
        description='ID of the user responsible for the activity'
    )
    estimated_date: date = Field(
        ...,
        description='Estimated date for the activity'
    )
    execution_date: Optional[date] = Field(
        None,
        description='Execution date of the activity'
    )
    budget: int = Field(
        ...,
        gt=0,
        description='Value authorized'
    )
    completed: Optional[bool] = Field(
        False,
        description='Whether the activity was completed'
    )
    budget: float = Field(
        ...,
        ge=0,
        description='Value authorized'
    )
    execution_value: Optional[float] = Field(
        0,
        ge=0,
        description='Value authorized'
    )
    comment: Optional[str] = Field(
        None,
        description='Comments about the activity'
    )


class ActivityCreate(ActivityBase):
    pass


class ActivityAuthorize(BaseModel):
    authorizeder: int = Field(
        None,
        ge=0,
        description='ID of the user authorizer responsible for the activity'
    )
    authorized: bool = Field(
        False,
        description='Whether the activity was authorized'
    )
    budget_authorized: float = Field(
        ...,
        ge=0,
        description='Value authorized'
    )


class Activity(ActivityBase, ActivityAuthorize):
    id_activity: int = Field(
        ...,
        gt=0
    )

    creation_date: Optional[date] = Field(
        ...,
        description='Creation date for the activity'
    )

    date_authorized: Optional[date] = Field(
        None,
        description='Date of the aut activity'
    )

    class Config:
        from_attributes = True


class ActivityFull(Activity):
    customer_trip: CustomerTripFull
    activity_type: ActivityTypeBase
    user_activities: UserBase
    authorizer_activities: Optional[UserBase]
