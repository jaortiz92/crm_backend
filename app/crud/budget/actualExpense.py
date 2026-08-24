"""
ActualExpense CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import ActualExpense as ActualExpenseModel
from app.schemas.budget import ActualExpenseCreate


def create_actual_expense(db: Session, actual_expense: ActualExpenseCreate) -> ActualExpenseModel:
    """Create a new actual expense record."""
    db_actual_expense = ActualExpenseModel(**actual_expense.model_dump())
    db.add(db_actual_expense)
    db.commit()
    db.refresh(db_actual_expense)
    return db_actual_expense


def create_actual_expenses_bulk(
    db: Session, actual_expenses: List[ActualExpenseCreate]
) -> List[ActualExpenseModel]:
    """Bulk insert actual expense records from ETL."""
    db_expenses = [ActualExpenseModel(**e.model_dump()) for e in actual_expenses]
    db.bulk_save_objects(db_expenses)
    db.commit()
    return db_expenses


def get_actual_expense_by_id(
    db: Session, id_actual_expense: int
) -> Optional[ActualExpenseModel]:
    """Get an actual expense by its ID."""
    return db.query(ActualExpenseModel).filter(
        ActualExpenseModel.id_actual_expense == id_actual_expense
    ).first()


def get_actual_expenses_by_cost_center(
    db: Session, id_cost_center: int, skip: int = 0, limit: int = 50
) -> List[ActualExpenseModel]:
    """Get actual expenses filtered by cost center."""
    return db.query(ActualExpenseModel).filter(
        ActualExpenseModel.id_cost_center == id_cost_center
    ).order_by(ActualExpenseModel.expense_date.desc()).offset(skip).limit(limit).all()


def get_actual_expenses(
    db: Session,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    id_cost_center: Optional[int] = None,
    expense_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[ActualExpenseModel]:
    """Get actual expenses with optional filters."""
    query = db.query(ActualExpenseModel)
    if date_ge is not None:
        query = query.filter(ActualExpenseModel.expense_date >= date_ge)
    if date_le is not None:
        query = query.filter(ActualExpenseModel.expense_date <= date_le)
    if id_cost_center is not None:
        query = query.filter(ActualExpenseModel.id_cost_center == id_cost_center)
    if expense_type is not None:
        query = query.filter(ActualExpenseModel.expense_type == expense_type)
    return query.order_by(ActualExpenseModel.expense_date.desc()).offset(skip).limit(limit).all()


def update_actual_expense(
    db: Session, id_actual_expense: int, actual_expense: ActualExpenseCreate
) -> Optional[ActualExpenseModel]:
    """Update an existing actual expense."""
    db_actual_expense = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.id_actual_expense == id_actual_expense
    ).first()
    if db_actual_expense:
        for key, value in actual_expense.model_dump().items():
            setattr(db_actual_expense, key, value)
        db.commit()
        db.refresh(db_actual_expense)
    return db_actual_expense


def delete_actual_expense(db: Session, id_actual_expense: int) -> bool:
    """Delete an actual expense by ID."""
    db_actual_expense = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.id_actual_expense == id_actual_expense
    ).first()
    if db_actual_expense:
        db.delete(db_actual_expense)
        db.commit()
        return True
    return False
