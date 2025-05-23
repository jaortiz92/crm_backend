# Python
from datetime import date, datetime
from typing import Optional, List, Dict

# Pydantic
from pydantic import BaseModel, Field

# App
from .invoice import InvoiceBase


class ShipmentBase(BaseModel):
    id_invoice: int = Field(
        ...,
        gt=0,
        description='ID of the invoice'
    )
    shipment_date: date = Field(
        ...,
        description='Date of the shipment'
    )
    carrier: str = Field(
        ...,
        max_length=50,
        description='Carrier name (max 50 characters)'
    )
    tracking_number: str = Field(
        ...,
        max_length=100,
        description='Tracking number (max 100 characters)'
    )
    estimated_delivery_date: date = Field(
        ...,
        description='Date the shipment will be received'
    )
    shipment_cost: float = Field(
        ...,
        description='Shipment value'
    )
    received: Optional[bool] = Field(
        False,
        description='The shipment was received'
    )
    received_date: Optional[date] = Field(
        None,
        description='Date the shipment was received'
    )
    details: Optional[str] = Field(
        None,
        max_length=255,
        description='Additional details (max 255 characters)'
    )


class ShipmentCreate(ShipmentBase):
    pass


class Shipment(ShipmentBase):
    id_shipment: int = Field(
        ...,
        gt=0
    )

    class Config:
        from_attributes = True


class ShipmentFull(Shipment):
    invoice: InvoiceBase
