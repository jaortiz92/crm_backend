# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class AdvanceBase(BaseModel):
    id_order: int = Field(...,
        gt=0,
        description='ID of the order'
    )
    payment_date: date = Field(...,
        description='Date of the payment'
    )
    advance_type: float = Field(...,
        ge=0,
        le=1,
        description='Type of the advance'
    )
    amount: int = Field(...,
        description='Amount of the advance'
    )
    payment: Optional[int] = Field(0,
        description='Payment made'
    )
    balance: Optional[int] = Field(
        None,
        description='Balance remaining'
    )
    paid: Optional[bool] = Field(False,
        description='Whether the advance is fully paid'
    )
    last_payment_date: Optional[date] = Field(None,
        description='Date of the last payment'
    )

class AdvanceCreate(AdvanceBase):
    pass

class Advance(AdvanceBase):
    id_advance: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
