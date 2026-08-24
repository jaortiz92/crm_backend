"""
Budget Scenario API Endpoints (What-If)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import BudgetScenario, BudgetScenarioCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_budget_scenario}", response_model=BudgetScenario)
def get_budget_scenario_by_id(
    id_budget_scenario: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a budget scenario by its ID."""
    db_scenario = crud.get_budget_scenario_by_id(db, id_budget_scenario)
    if db_scenario is None:
        Exceptions.register_not_found("BudgetScenario", id_budget_scenario)
    return db_scenario


@router.get("/budget/{id_budget}", response_model=List[BudgetScenario])
def get_budget_scenarios_by_budget(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all scenarios for a given budget."""
    return crud.get_budget_scenarios_by_budget(db, id_budget)


@router.get("/", response_model=List[BudgetScenario])
def get_budget_scenarios(
    scenario_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get budget scenarios with optional filters."""
    return crud.get_budget_scenarios(
        db, scenario_type=scenario_type, is_active=is_active,
        skip=skip, limit=limit,
    )


@router.post("/", response_model=BudgetScenario)
def create_budget_scenario(
    budget_scenario: BudgetScenarioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new budget scenario for what-if simulation."""
    budget_obj = crud.get_budget_by_id(db, budget_scenario.id_budget)
    if budget_obj is None:
        Exceptions.register_not_found("Budget", budget_scenario.id_budget)
    return crud.create_budget_scenario(db, budget_scenario)


@router.put("/{id_budget_scenario}", response_model=BudgetScenario)
def update_budget_scenario(
    id_budget_scenario: int,
    budget_scenario: BudgetScenarioCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing budget scenario."""
    db_scenario = crud.update_budget_scenario(db, id_budget_scenario, budget_scenario)
    if db_scenario is None:
        Exceptions.register_not_found("BudgetScenario", id_budget_scenario)
    return db_scenario


@router.delete("/{id_budget_scenario}")
def delete_budget_scenario(
    id_budget_scenario: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a budget scenario by ID."""
    success = crud.delete_budget_scenario(db, id_budget_scenario)
    if not success:
        Exceptions.register_not_found("BudgetScenario", id_budget_scenario)
    return {"message": "Budget scenario deleted successfully"}
