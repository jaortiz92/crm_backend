"""
Budget Line API Endpoints
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import BudgetLine, BudgetLineCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_budget_line}", response_model=BudgetLine)
def get_budget_line_by_id(
    id_budget_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a budget line by its ID."""
    db_line = crud.get_budget_line_by_id(db, id_budget_line)
    if db_line is None:
        Exceptions.register_not_found("BudgetLine", id_budget_line)
    return db_line


@router.get("/budget/{id_budget}", response_model=List[BudgetLine])
def get_budget_lines_by_budget(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all budget lines for a given budget."""
    return crud.get_budget_lines_by_budget(db, id_budget)


@router.post("/", response_model=BudgetLine)
def create_budget_line(
    budget_line: BudgetLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new budget line."""
    budget_obj = crud.get_budget_by_id(db, budget_line.id_budget)
    if budget_obj is None:
        Exceptions.register_not_found("Budget", budget_line.id_budget)
    cost_center = crud.get_cost_center_by_id(db, budget_line.id_cost_center)
    if cost_center is None:
        Exceptions.register_not_found("CostCenter", budget_line.id_cost_center)
    return crud.create_budget_line(db, budget_line)


@router.put("/{id_budget_line}", response_model=BudgetLine)
def update_budget_line(
    id_budget_line: int,
    budget_line: BudgetLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing budget line."""
    db_line = crud.update_budget_line(db, id_budget_line, budget_line)
    if db_line is None:
        Exceptions.register_not_found("BudgetLine", id_budget_line)
    return db_line


@router.delete("/{id_budget_line}")
def delete_budget_line(
    id_budget_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a budget line by ID."""
    success = crud.delete_budget_line(db, id_budget_line)
    if not success:
        Exceptions.register_not_found("BudgetLine", id_budget_line)
    return {"message": "Budget line deleted successfully"}
