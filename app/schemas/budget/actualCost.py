"""
ActualCost Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActualCostBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    cost_date: date = Field(..., description="Date of the cost")
    cost_type: str = Field(..., max_length=60, description="Category of cost")
    description: Optional[str] = Field(None, description="Detail of the cost")
    amount: float = Field(..., ge=0, description="Cost amount")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class ActualCostCreate(ActualCostBase):
    pass


class ActualCost(ActualCostBase):
    id_actual_cost: int = Field(..., gt=0)
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
