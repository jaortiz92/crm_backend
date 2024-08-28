# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class TaskBase(BaseModel):
    id_client: int = Field(...,
        gt=0,
        description='ID of the client'
    )
    id_creator_user: int = Field(...,
        gt=0,
        description='ID of the user who created the task'
    )
    id_responsible_user: int = Field(...,
        gt=0,
        description='ID of the user responsible for the task'
    )
    creation_date: date = Field(...,
        description='Creation date of the task'
    )
    task_description: str = Field(...,
        description='Description of the task'
    )
    completed: Optional[bool] = Field(False,
        description='Whether the task was completed'
    )
    closing_date: Optional[date] = Field(None,
        description='Closing date of the task'
    )
    comment: Optional[str] = Field(None,
        description='Comments about the task'
    )

class TaskCreate(TaskBase):
    pass

class Task(TaskBase):
    id_task: int = Field(...,
        gt=0,
        description='ID of the task'
    )

    class Config:
        orm_mode = True
