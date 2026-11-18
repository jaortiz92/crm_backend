"""
ActualCost Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActualCostBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    document_number: str = Field(..., max_length=50, description="Invoice/document number")
    id_reference: Optional[int] = Field(None, gt=0, description="FK to product reference")
    quantity: int = Field(..., ge=0, description="Quantity of units")
    unit_cost: float = Field(..., ge=0, description="Cost per unit")
    cost_date: date = Field(..., description="Date of the cost")
    cost_type: str = Field(..., max_length=60, description="Category of cost")
    amount: float = Field(..., ge=0, description="Total cost (quantity * unit_cost)")
    description: Optional[str] = Field(None, description="Optional description of the cost")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class ActualCostCreate(ActualCostBase):
    pass


class ActualCost(ActualCostBase):
    id_actual_cost: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

