# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class ActivityBase(BaseModel):
    client_trip_id: int = Field(...,
        gt=0,
        description='ID of the client trip'
    )
    activity_type_id: int = Field(...,
        gt=0,
        description='ID of the activity type'
    )
    user_id: int = Field(...,
        gt=0,
        description='ID of the user responsible for the activity'
    )
    estimated_date: date = Field(...,
        description='Estimated date for the activity'
    )
    execution_date: Optional[date] = Field(None,
        description='Execution date of the activity'
    )
    completed: Optional[bool] = Field(False,
        description='Whether the activity was completed'
    )
    comment: Optional[str] = Field(None,
        description='Comments about the activity'
    )

class ActivityCreate(ActivityBase):
    pass

class Activity(ActivityBase):
    id_activity: int = Field(..., 
        gt=0
    )

    class Config:
        orm_mode = True
