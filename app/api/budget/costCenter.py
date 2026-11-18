"""
Cost Center API Endpoints
"""

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import CostCenter, CostCenterCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_cost_center}", response_model=CostCenter)
def get_cost_center_by_id(
    id_cost_center: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a cost center by its ID.

    Parameters:
    - id_cost_center: int (path parameter)

    Returns the cost center object.
    """
    db_cost_center = crud.get_cost_center_by_id(db, id_cost_center)
    if db_cost_center is None:
        Exceptions.register_not_found("CostCenter", id_cost_center)
    return db_cost_center


@router.get("/", response_model=List[CostCenter])
def get_cost_centers(
    skip: int = 0,
    limit: int = 50,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all cost centers with optional active filter.

    Parameters:
    - skip: int (default: 0)
    - limit: int (default: 50)
    - is_active: Optional[bool]
    """
    return crud.get_cost_centers(db, skip=skip, limit=limit, is_active=is_active)


@router.post("/", response_model=CostCenter)
def create_cost_center(
    cost_center: CostCenterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new cost center.

    Parameters:
    - cost_center: CostCenterCreate (request body)
    """
    existing = crud.get_cost_center_by_code(db, cost_center.cost_center_code)
    if existing:
        Exceptions.register_already_registered("CostCenter", cost_center.cost_center_code)
    return crud.create_cost_center(db, cost_center)


@router.put("/{id_cost_center}", response_model=CostCenter)
def update_cost_center(
    id_cost_center: int,
    cost_center: CostCenterCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update an existing cost center.

    Parameters:
    - id_cost_center: int (path parameter)
    - cost_center: CostCenterCreate (request body)
    """
    db_cost_center = crud.update_cost_center(db, id_cost_center, cost_center)
    if db_cost_center is None:
        Exceptions.register_not_found("CostCenter", id_cost_center)
    return db_cost_center


@router.delete("/{id_cost_center}")
def delete_cost_center(
    id_cost_center: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a cost center by ID.

    Parameters:
    - id_cost_center: int (path parameter)
    """
    success = crud.delete_cost_center(db, id_cost_center)
    if not success:
        Exceptions.register_not_found("CostCenter", id_cost_center)
    return {"message": "Cost center deleted successfully"}
