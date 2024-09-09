# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .department import DepartmentBase

class CityBase(BaseModel):
    id_department: int = Field(...,
            gt=0,
            description='ID of the department the city belongs to'
    )
    city_code: str = Field(...,
        max_length=5,
        description='City code (max 5 characters)'
    )
    city_name: str = Field(...,
        max_length=80,
        description='City name (max 80 characters)'
    )
    latitude: float = Field(...,
        ge=-90,
        le=90,
        description='Latitude of the city'
    )
    longitude: float = Field(
        ..., 
        ge=-180,
        le=180,
        description='Longitude of the city'
    )

class CityCreate(CityBase):
    pass

class City(CityBase):
    id_city: int = Field(...,
        gt=0
    )

    class Config:
        from_attributes = True

class CityFull(City):
    department: Optional[DepartmentBase]