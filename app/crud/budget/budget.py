"""
Budget CRUD Operations
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import Budget as BudgetModel
from app.schemas.budget import BudgetCreate


def create_budget(db: Session, budget: BudgetCreate) -> BudgetModel:
    """Create a new budget."""
    db_budget = BudgetModel(**budget.model_dump())
    db.add(db_budget)
    db.commit()
    db.refresh(db_budget)
    return db_budget


def get_budget_by_id(db: Session, id_budget: int) -> Optional[BudgetModel]:
    """Get a budget by its ID."""
    return db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()


def get_budgets(
    db: Session,
    budget_year: Optional[int] = None,
    status: Optional[str] = None,
    is_scenario: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[BudgetModel]:
    """Get budgets with optional filters."""
    query = db.query(BudgetModel)
    if budget_year is not None:
        query = query.filter(BudgetModel.budget_year == budget_year)
    if status is not None:
        query = query.filter(BudgetModel.status == status)
    if is_scenario is not None:
        query = query.filter(BudgetModel.is_scenario == is_scenario)
    return query.order_by(BudgetModel.created_at.desc()).offset(skip).limit(limit).all()


def update_budget(
    db: Session, id_budget: int, budget: BudgetCreate
) -> Optional[BudgetModel]:
    """Update an existing budget."""
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget:
        for key, value in budget.model_dump().items():
            setattr(db_budget, key, value)
        db.commit()
        db.refresh(db_budget)
    return db_budget


def delete_budget(db: Session, id_budget: int) -> bool:
    """Delete a budget by ID."""
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget:
        db.delete(db_budget)
        db.commit()
        return True
    return False
