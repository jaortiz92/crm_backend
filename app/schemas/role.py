# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class RoleBase(BaseModel):
    role_name: str = Field(...,
        max_length=50,
        description='Role name (max 50 characters)'
    )
    access_type: str = Field(...,
        max_length=10,
        description='Access type (max 10 characters)'
    )

class RoleCreate(RoleBase):
    pass

class Role(RoleBase):
    id_role: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
