# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field


class ClientTripBase(BaseModel):
    client_id: int = Field(...,
        gt=0,
        description='ID of the client'
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
        description='Whether the client placed an order'
    )
    comment: Optional[str] = Field(None,
        description='Comments about the trip'
    )

class ClientTripCreate(ClientTripBase):
    pass

class ClientTrip(ClientTripBase):
    id_client_trip: int = Field(..., 
        gt=0
    )

    class Config:
        orm_mode = True
