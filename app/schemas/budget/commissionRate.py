"""
CommissionRate Schemas
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class CommissionRateBase(BaseModel):
    id_line: Optional[int] = Field(None, description="FK lines.id_line. NULL = global fallback rate")
    rate_name: Optional[str] = Field(None, max_length=120)
    commission_pct: float = Field(..., ge=0, le=100, description="Commission % of net collected (0-100)")
    date_from: date
    date_to: date
    is_active: Optional[bool] = Field(True)

    model_config = ConfigDict(from_attributes=True)


class CommissionRateCreate(CommissionRateBase):
    pass


class CommissionRateUpdate(BaseModel):
    """Partial update: every field optional; validators of BR-12/13 re-run on merge."""
    id_line: Optional[int] = None
    rate_name: Optional[str] = Field(None, max_length=120)
    commission_pct: Optional[float] = Field(None, ge=0, le=100)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    is_active: Optional[bool] = None


class CommissionRate(CommissionRateBase):
    id_commission_rate: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
