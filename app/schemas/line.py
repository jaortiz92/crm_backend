# Python
from typing import Optional, List, Dict
from datetime import date

# Pydantic
from pydantic import BaseModel, EmailStr, Field

class LineBase(BaseModel):
    line_name: str = Field(...,
        max_length=100,
        description='Line name (max 100 characters)'
    )

class LineCreate(LineBase):
    pass

class Line(LineBase):
    id_line: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
