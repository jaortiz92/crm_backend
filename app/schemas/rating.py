# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class RatingBase(BaseModel):
    id_client: int = Field(...,
        gt=0,
        description='ID of the client'
    )
    id_rating_category: int = Field(...,
        gt=0,
        description='ID of the rating category'
    )
    date_updated: date = Field(...,
        description='Date of the rating'
    )
    comments: Optional[str] = Field(None,
        description='Comments about the rating'
    )

class RatingCreate(RatingBase):
    pass

class Rating(RatingBase):
    id_rating: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
