# Python
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

class RatingCategoryBase(BaseModel):
    rating_category: str = Field(...,
        max_length=20,
        description='Rating category (max 20 characters)'
    )
    level: int = Field(
        ..., 
        description='Rating level'
    )

class RatingCategoryCreate(RatingCategoryBase):
    pass

class RatingCategory(RatingCategoryBase):
    id_rating_category: int = Field(..., 
        gt=0
    )

    class Config:
        orm_mode = True