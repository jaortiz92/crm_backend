"""
Budget API Endpoints

Root-level budget endpoints (no additional sub-prefix).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import Budget, BudgetCreate, BudgetFull
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_budget}", response_model=Budget)
def get_budget_by_id(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a budget by its ID."""
    db_budget = crud.get_budget_by_id(db, id_budget)
    if db_budget is None:
        Exceptions.register_not_found("Budget", id_budget)
    return db_budget


@router.get("/full/{id_budget}", response_model=BudgetFull)
def get_budget_full(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a budget with all its budget lines."""
    db_budget = crud.get_budget_by_id(db, id_budget)
    if db_budget is None:
        Exceptions.register_not_found("Budget", id_budget)
    return db_budget


@router.get("/", response_model=List[Budget])
def get_budgets(
    budget_year: Optional[int] = None,
    status: Optional[str] = None,
    is_scenario: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get budgets with optional filters.

    Parameters:
    - budget_year: Optional[int] - filter by fiscal year
    - status: Optional[str] - filter by status (draft, active, archived)
    - is_scenario: Optional[bool] - filter by scenario flag
    - skip: int (default: 0)
    - limit: int (default: 50)
    """
    return crud.get_budgets(
        db, budget_year=budget_year, status=status,
        is_scenario=is_scenario, skip=skip, limit=limit,
    )


@router.post("/", response_model=Budget)
def create_budget(
    budget_data: BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new budget."""
    return crud.create_budget(db, budget_data)


@router.put("/{id_budget}", response_model=Budget)
def update_budget(
    id_budget: int,
    budget_data: BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing budget."""
    db_budget = crud.update_budget(db, id_budget, budget_data)
    if db_budget is None:
        Exceptions.register_not_found("Budget", id_budget)
    return db_budget


@router.delete("/{id_budget}")
def delete_budget(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physically delete a DRAFT budget (backend.02_14, safe delete).

    BR-DEL-01: only status == 'draft' is deletable; active/closed answer
    400 "Only draft budgets can be deleted" (raised inside the CRUD,
    re-raised verbatim — never mapped to 404) with the row untouched.
    BR-DEL-02: the budget's own budget_lines and budget_scenarios are
    deleted too; BR-DEL-03: guest clones survive with
    parent_budget_id = NULL (D-4). All of it runs in ONE transaction with
    a single commit (BR-DEL-04 / T-05): any failure rolls back and leaves
    no partial delete. Status is re-validated server-side at delete time
    (BR-DEL-05, last-write-wins). Missing id -> 404 (existing
    Exceptions.register_not_found convention). 200 shape is backward
    compatible."""
    try:
        success = crud.delete_budget(db, id_budget)
        if not success:
            Exceptions.register_not_found("Budget", id_budget)
        return {"message": "Budget deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting budget: {str(e)}",
        )
