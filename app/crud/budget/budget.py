"""
Budget CRUD Operations
"""

from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.budget import Budget as BudgetModel
from app.models.budget import BudgetLine as BudgetLineModel
from app.models.budget import BudgetScenario as BudgetScenarioModel
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
    """Delete a DRAFT budget by ID (backend.02_14, safe physical delete).

    Missing row -> False (the API layer keeps its 404 convention).
    BR-DEL-01: any status other than 'draft' raises 400 with no mutation
    (active = the year's live target, closed = was a target; neither is
    deletable). BR-DEL-02: own rows referencing the budget (budget_lines,
    budget_scenarios, legacy NOT NULL FKs) are bulk-deleted first.
    BR-DEL-03: guest clones survive, orphaned via parent_budget_id = NULL.
    BR-DEL-04: exactly ONE commit at the end (T-05); any failure before it
    leaves the transaction rollback-able (no partial delete)."""
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget is None:
        return False

    # BR-DEL-01: server-side eligibility re-validated at delete time
    # (resolves the GET->DELETE window, BR-DEL-05 last-write-wins).
    if db_budget.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft budgets can be deleted",
        )

    # BR-DEL-02: physical cascade over the budget's own rows.
    db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget == id_budget
    ).delete(synchronize_session=False)
    db.query(BudgetScenarioModel).filter(
        BudgetScenarioModel.id_budget == id_budget
    ).delete(synchronize_session=False)

    # BR-DEL-03: detach clones cloned from this draft (D-4).
    db.query(BudgetModel).filter(
        BudgetModel.parent_budget_id == id_budget
    ).update({"parent_budget_id": None}, synchronize_session=False)

    db.delete(db_budget)

    # BR-DEL-04: the only commit of the whole operation.
    db.commit()
    return True
