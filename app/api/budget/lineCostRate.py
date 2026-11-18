"""
Line Cost Rate API Endpoints

Master catalog of budgeted COGS % per product line (Pilar 1 - P&L).
Mirrors the budgetScenario.py style: JWT on every route,
Exceptions.register_not_found on 404, filters as query params, skip/limit.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import LineCostRate, LineCostRateCreate, LineCostRateUpdate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/", response_model=List[LineCostRate])
def get_line_cost_rates(
    id_line: Optional[int] = Query(
        None, description="Only rates of this product line"),
    active_only: bool = Query(
        False, description="Only active rates"),
    date: Optional[date] = Query(
        None,
        description="Only rates in force at this date (validity per spec §4.4.1)"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List line cost rates with optional filters."""
    return crud.get_line_cost_rates(
        db, id_line=id_line, active_only=active_only, date_ref=date,
        skip=skip, limit=limit,
    )


@router.get("/{id_line_cost_rate}", response_model=LineCostRate)
def get_line_cost_rate_by_id(
    id_line_cost_rate: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a line cost rate by its ID."""
    db_rate = crud.get_line_cost_rate_by_id(db, id_line_cost_rate)
    if db_rate is None:
        Exceptions.register_not_found("LineCostRate", id_line_cost_rate)
    return db_rate


@router.post("/", response_model=LineCostRate)
def create_line_cost_rate(
    line_cost_rate: LineCostRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a rate. Validates BR-12 (period) / BR-13 (overlap) -> 400 (E-4/E-5)."""
    if line_cost_rate.id_line is not None:
        line_obj = crud.get_line_by_id(db, line_cost_rate.id_line)
        if line_obj is None:
            Exceptions.register_not_found("Line", line_cost_rate.id_line)
    return crud.create_line_cost_rate(db, line_cost_rate)


@router.put("/{id_line_cost_rate}", response_model=LineCostRate)
def update_line_cost_rate(
    id_line_cost_rate: int,
    line_cost_rate: LineCostRateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update (merge non-None fields) + same validations; overlap check
    excludes the row itself."""
    if line_cost_rate.id_line is not None:
        line_obj = crud.get_line_by_id(db, line_cost_rate.id_line)
        if line_obj is None:
            Exceptions.register_not_found("Line", line_cost_rate.id_line)
    db_rate = crud.update_line_cost_rate(db, id_line_cost_rate, line_cost_rate)
    if db_rate is None:
        Exceptions.register_not_found("LineCostRate", id_line_cost_rate)
    return db_rate


@router.delete("/{id_line_cost_rate}")
def delete_line_cost_rate(
    id_line_cost_rate: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete (audit-friendly deactivation: PUT is_active=false)."""
    db_rate = crud.delete_line_cost_rate(db, id_line_cost_rate)
    if db_rate is None:
        Exceptions.register_not_found("LineCostRate", id_line_cost_rate)
    return {"message": "Line cost rate deleted successfully"}
