"""
BudgetScenario Schemas
"""

from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class BudgetScenarioBase(BaseModel):
    scenario_name: str = Field(..., max_length=120, description="Name of the scenario")
    id_budget: int = Field(..., gt=0, description="FK to base budget")
    scenario_type: str = Field(
        ..., max_length=40,
        description="Type: freight_increase, payment_terms_change, etc."
    )
    parameters: Optional[Dict[str, Any]] = Field(
        None,
        description="Scenario parameters as JSON"
    )
    results: Optional[Dict[str, Any]] = Field(
        None,
        description="Scenario results as JSON"
    )
    is_active: Optional[bool] = Field(True, description="Whether scenario is active")


class BudgetScenarioCreate(BudgetScenarioBase):
    pass


class BudgetScenario(BudgetScenarioBase):
    id_budget_scenario: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
