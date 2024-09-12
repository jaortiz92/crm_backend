# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, EmailStr, Field

# App
from .customerTrip import CustomerTripFull
from .user import UserBase
from .paymentMethod import PaymentMethodBase


class OrderBase(BaseModel):
    id_customer_trip: int = Field(...,
        gt=0,
        description='ID of the customer trip'
    )
    id_seller: int = Field(...,
        gt=0,
        description='ID of the seller'
    )
    date_order: date = Field(...,
        description='Date of the order'
    )
    id_payment_method: int = Field(...,
        gt=0,
        description='ID of the payment method'
    )
    quantities: int = Field(...,
        description='Quantities ordered'
    )
    system_quantities: Optional[int] = Field(None,
        description='Quantities in the system'
    )
    value_without_tax: int = Field(...,
        description='Value without tax'
    )
    value_with_tax: int = Field(...,
        description='Value with tax'
    )
    delivery_date: date = Field(...,
        description='Date of delivery'
    )

class OrderCreate(OrderBase):
    pass

class Order(OrderBase):
    id_order: int = Field(...,
        gt=0
    )

    class Config:
        from_attributes = True

class OrderFull(Order):
    customer_trip: CustomerTripFull
    seller: UserBase
    payment_method: PaymentMethodBase