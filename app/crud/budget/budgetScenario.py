"""
BudgetScenario CRUD Operations
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import BudgetScenario as BudgetScenarioModel
from app.schemas.budget import BudgetScenarioCreate


def create_budget_scenario(
    db: Session, budget_scenario: BudgetScenarioCreate
) -> BudgetScenarioModel:
    """Create a new budget scenario."""
    db_scenario = BudgetScenarioModel(**budget_scenario.model_dump())
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario


def get_budget_scenario_by_id(
    db: Session, id_budget_scenario: int
) -> Optional[BudgetScenarioModel]:
    """Get a budget scenario by its ID."""
    return db.query(BudgetScenarioModel).filter(
        BudgetScenarioModel.id_budget_scenario == id_budget_scenario
    ).first()


def get_budget_scenarios_by_budget(
    db: Session, id_budget: int
) -> List[BudgetScenarioModel]:
    """Get all scenarios for a given budget."""
    return db.query(BudgetScenarioModel).filter(
        BudgetScenarioModel.id_budget == id_budget
    ).order_by(BudgetScenarioModel.created_at.desc()).all()


def get_budget_scenarios(
    db: Session,
    scenario_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[BudgetScenarioModel]:
    """Get budget scenarios with optional filters."""
    query = db.query(BudgetScenarioModel)
    if scenario_type is not None:
        query = query.filter(BudgetScenarioModel.scenario_type == scenario_type)
    if is_active is not None:
        query = query.filter(BudgetScenarioModel.is_active == is_active)
    return query.order_by(
        BudgetScenarioModel.created_at.desc()
    ).offset(skip).limit(limit).all()


def update_budget_scenario(
    db: Session, id_budget_scenario: int, budget_scenario: BudgetScenarioCreate
) -> Optional[BudgetScenarioModel]:
    """Update an existing budget scenario."""
    db_scenario = db.query(BudgetScenarioModel).filter(
        BudgetScenarioModel.id_budget_scenario == id_budget_scenario
    ).first()
    if db_scenario:
        for key, value in budget_scenario.model_dump().items():
            setattr(db_scenario, key, value)
        db.commit()
        db.refresh(db_scenario)
    return db_scenario


def delete_budget_scenario(db: Session, id_budget_scenario: int) -> bool:
    """Delete a budget scenario by ID."""
    db_scenario = db.query(BudgetScenarioModel).filter(
        BudgetScenarioModel.id_budget_scenario == id_budget_scenario
    ).first()
    if db_scenario:
        db.delete(db_scenario)
        db.commit()
        return True
    return False
