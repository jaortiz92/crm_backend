"""
Actual Expense API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import ActualExpense, ActualExpenseCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_actual_expense}", response_model=ActualExpense)
def get_actual_expense_by_id(
    id_actual_expense: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an actual expense by its ID."""
    db_expense = crud.get_actual_expense_by_id(db, id_actual_expense)
    if db_expense is None:
        Exceptions.register_not_found("ActualExpense", id_actual_expense)
    return db_expense


@router.get("/", response_model=List[ActualExpense])
def get_actual_expenses(
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    id_cost_center: Optional[int] = None,
    expense_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get actual expenses with optional filters.

    Parameters:
    - date_ge: Optional[date] - expenses from this date onwards
    - date_le: Optional[date] - expenses up to this date
    - id_cost_center: Optional[int] - filter by cost center
    - expense_type: Optional[str] - filter by expense type
    - skip: int (default: 0)
    - limit: int (default: 50)
    """
    return crud.get_actual_expenses(
        db, date_ge=date_ge, date_le=date_le,
        id_cost_center=id_cost_center, expense_type=expense_type,
        skip=skip, limit=limit,
    )


@router.get("/cost-center/{id_cost_center}", response_model=List[ActualExpense])
def get_actual_expenses_by_cost_center(
    id_cost_center: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get actual expenses filtered by cost center."""
    return crud.get_actual_expenses_by_cost_center(db, id_cost_center, skip=skip, limit=limit)


@router.post("/", response_model=ActualExpense)
def create_actual_expense(
    actual_expense: ActualExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new actual expense record."""
    cost_center = crud.get_cost_center_by_id(db, actual_expense.id_cost_center)
    if cost_center is None:
        Exceptions.register_not_found("CostCenter", actual_expense.id_cost_center)
    return crud.create_actual_expense(db, actual_expense)


@router.put("/{id_actual_expense}", response_model=ActualExpense)
def update_actual_expense(
    id_actual_expense: int,
    actual_expense: ActualExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing actual expense."""
    db_expense = crud.update_actual_expense(db, id_actual_expense, actual_expense)
    if db_expense is None:
        Exceptions.register_not_found("ActualExpense", id_actual_expense)
    return db_expense


@router.delete("/{id_actual_expense}")
def delete_actual_expense(
    id_actual_expense: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an actual expense by ID."""
    success = crud.delete_actual_expense(db, id_actual_expense)
    if not success:
        Exceptions.register_not_found("ActualExpense", id_actual_expense)
    return {"message": "Actual expense deleted successfully"}
