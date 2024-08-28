# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

class ShipmentBase(BaseModel):
    id_invoice: int = Field(...,
        gt=0,
        description='ID of the invoice'
    )
    shipment_date: date = Field(...,
        description='Date of the shipment'
    )
    carrier: str = Field(...,
        max_length=50,
        description='Carrier name (max 50 characters)'
    )
    tracking_number: str = Field(...,
        max_length=100,
        description='Tracking number (max 100 characters)'
    )
    received_date: date = Field(...,
        description='Date the shipment was received'
    )
    shipment_value: float = Field(...,
        description='Shipment value'
    )
    details: Optional[str] = Field(None,
        max_length=255,
        description='Additional details (max 255 characters)'
    )

class ShipmentCreate(ShipmentBase):
    pass

class Shipment(ShipmentBase):
    id_shipment: int = Field(...,
        gt=0
    )

    class Config:
        orm_mode = True
