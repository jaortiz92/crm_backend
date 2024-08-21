# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field


class CustomerTripBase(BaseModel):
    Customer_id: int = Field(...,
        gt=0,
        description='ID of the Customer'
    )
    seller_id: int = Field(...,
        gt=0,
        description='ID of the seller'
    )
    collection_id: int = Field(...,
        gt=0,
        description='ID of the collection'
    )
    budget: float = Field(...,
        description='Budget for the trip'
    )
    ordered: Optional[bool] = Field(None,
        description='Whether the Customer placed an order'
    )
    comment: Optional[str] = Field(None,
        description='Comments about the trip'
    )

class CustomerTripCreate(CustomerTripBase):
    pass

class CustomerTrip(CustomerTripBase):
    id_Customer_trip: int = Field(..., 
        gt=0
    )

    class Config:
        orm_mode = True
