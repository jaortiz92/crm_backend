# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .ratingCategory import RatingCategoryBase
from .customer import CustomerBase


class RatingBase(BaseModel):
    id_customer: int = Field(...,
        gt=0,
        description='ID of the customer'
    )
    id_rating_category: int = Field(...,
        gt=0,
        description='ID of the rating category'
    )
    date_updated: Optional[date] = Field(...,
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
        from_attributes = True


class RatingFull(Rating):
    customer: CustomerBase
    rating_category: RatingCategoryBase