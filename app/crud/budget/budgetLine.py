"""
BudgetLine CRUD Operations
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import BudgetLine as BudgetLineModel
from app.schemas.budget import BudgetLineCreate


def create_budget_line(db: Session, budget_line: BudgetLineCreate) -> BudgetLineModel:
    """Create a new budget line."""
    db_budget_line = BudgetLineModel(**budget_line.model_dump())
    db.add(db_budget_line)
    db.commit()
    db.refresh(db_budget_line)
    return db_budget_line


def create_budget_lines_bulk(
    db: Session, budget_lines: List[BudgetLineCreate]
) -> List[BudgetLineModel]:
    """Bulk insert budget lines."""
    db_lines = [BudgetLineModel(**bl.model_dump()) for bl in budget_lines]
    db.bulk_save_objects(db_lines)
    db.commit()
    return db_lines


def get_budget_line_by_id(
    db: Session, id_budget_line: int
) -> Optional[BudgetLineModel]:
    """Get a budget line by its ID."""
    return db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()


def get_budget_lines_by_budget(
    db: Session, id_budget: int
) -> List[BudgetLineModel]:
    """Get all budget lines for a given budget."""
    return db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget == id_budget
    ).order_by(BudgetLineModel.month, BudgetLineModel.id_cost_center).all()


def get_budget_lines_by_cost_center(
    db: Session, id_cost_center: int, id_budget: Optional[int] = None
) -> List[BudgetLineModel]:
    """Get budget lines filtered by cost center and optionally by budget."""
    query = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_cost_center == id_cost_center
    )
    if id_budget is not None:
        query = query.filter(BudgetLineModel.id_budget == id_budget)
    return query.order_by(BudgetLineModel.month).all()


def update_budget_line(
    db: Session, id_budget_line: int, budget_line: BudgetLineCreate
) -> Optional[BudgetLineModel]:
    """Update an existing budget line."""
    db_budget_line = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()
    if db_budget_line:
        for key, value in budget_line.model_dump().items():
            setattr(db_budget_line, key, value)
        db.commit()
        db.refresh(db_budget_line)
    return db_budget_line


def delete_budget_line(db: Session, id_budget_line: int) -> bool:
    """Delete a budget line by ID."""
    db_budget_line = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()
    if db_budget_line:
        db.delete(db_budget_line)
        db.commit()
        return True
    return False
