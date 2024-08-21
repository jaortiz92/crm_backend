# Python
from datetime import date, datetime
from typing import Optional, List, Dict, Literal

# Pydantic
from pydantic import BaseModel, Field

class CreditBase(BaseModel):
    invoice_id: int = Field(...,
        gt=0,
        description='ID of the invoice'
    )
    term: int = Field(...,
        description='Credit term in months'
    )
    credit_value: float = Field(...,
        description='Credit value'
    )
    payment_value: float = Field(...,
        description='Payment value'
    )
    balance: Optional[float] = Field(...,
        description='Balance remaining'
    )
    paid: Optional[bool] = Field(False,
        description='Whether the credit is fully paid'
    )
    last_payment_date: Optional[date] = Field(None,
        description='Date of the last payment'
    )

class CreditCreate(CreditBase):
    pass

class Credit(CreditBase):
    id_credit: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
