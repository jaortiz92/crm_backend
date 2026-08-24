"""
Actual Cost API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import ActualCost, ActualCostCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_actual_cost}", response_model=ActualCost)
def get_actual_cost_by_id(
    id_actual_cost: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an actual cost by its ID."""
    db_cost = crud.get_actual_cost_by_id(db, id_actual_cost)
    if db_cost is None:
        Exceptions.register_not_found("ActualCost", id_actual_cost)
    return db_cost


@router.get("/", response_model=List[ActualCost])
def get_actual_costs(
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    id_cost_center: Optional[int] = None,
    cost_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get actual costs with optional filters."""
    return crud.get_actual_costs(
        db, date_ge=date_ge, date_le=date_le,
        id_cost_center=id_cost_center, cost_type=cost_type,
        skip=skip, limit=limit,
    )


@router.get("/cost-center/{id_cost_center}", response_model=List[ActualCost])
def get_actual_costs_by_cost_center(
    id_cost_center: int,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get actual costs filtered by cost center."""
    return crud.get_actual_costs_by_cost_center(db, id_cost_center, skip=skip, limit=limit)


@router.post("/", response_model=ActualCost)
def create_actual_cost(
    actual_cost: ActualCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new actual cost record."""
    cost_center = crud.get_cost_center_by_id(db, actual_cost.id_cost_center)
    if cost_center is None:
        Exceptions.register_not_found("CostCenter", actual_cost.id_cost_center)
    return crud.create_actual_cost(db, actual_cost)


@router.put("/{id_actual_cost}", response_model=ActualCost)
def update_actual_cost(
    id_actual_cost: int,
    actual_cost: ActualCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing actual cost."""
    db_cost = crud.update_actual_cost(db, id_actual_cost, actual_cost)
    if db_cost is None:
        Exceptions.register_not_found("ActualCost", id_actual_cost)
    return db_cost


@router.delete("/{id_actual_cost}")
def delete_actual_cost(
    id_actual_cost: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an actual cost by ID."""
    success = crud.delete_actual_cost(db, id_actual_cost)
    if not success:
        Exceptions.register_not_found("ActualCost", id_actual_cost)
    return {"message": "Actual cost deleted successfully"}
