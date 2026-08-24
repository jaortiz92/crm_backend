"""
CostCenter Schemas
"""

from typing import Optional

from pydantic import BaseModel, Field


class CostCenterBase(BaseModel):
    cost_center_code: str = Field(
        ..., max_length=20,
        description="Unique code aligned with the accounting system"
    )
    cost_center_name: str = Field(
        ..., max_length=120,
        description="Name of the cost center"
    )
    id_zone: Optional[int] = Field(
        None, gt=0,
        description="FK to zone"
    )
    id_area: Optional[int] = Field(
        None, gt=0,
        description="FK to area"
    )
    id_line: Optional[int] = Field(
        None, gt=0,
        description="FK to product line"
    )
    is_active: Optional[bool] = Field(
        True,
        description="Whether the cost center is active"
    )
    description: Optional[str] = Field(
        None,
        description="Optional description"
    )


class CostCenterCreate(CostCenterBase):
    pass


class CostCenter(CostCenterBase):
    id_cost_center: int = Field(..., gt=0)

    class Config:
        from_attributes = True
