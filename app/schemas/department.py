# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class DepartmentBase(BaseModel):
    department_code: str = Field(..., 
        max_length=2,
        description='Department code (max 2 characters)'
    )
    department_name: str = Field(...,
        max_length=80,
        description='Department name (max 80 characters)'
    )

class DepartmentCreate(DepartmentBase):
    pass

class Department(DepartmentBase):
    id_department: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
