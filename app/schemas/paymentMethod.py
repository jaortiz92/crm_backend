
# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class PaymentMethodBase(BaseModel):
    payment_method_name: str = Field(...,
        max_length=100,
        description='Payment method name (max 100 characters)'
    )

class PaymentMethodCreate(PaymentMethodBase):
    pass

class PaymentMethod(PaymentMethodBase):
    id_payment_method: int = Field(...,
        gt=0,
    )

    class Config:
        orm_mode = True
