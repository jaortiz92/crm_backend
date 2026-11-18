"""
Commission Rate API Endpoints

Master catalog of commission % per product line (Pilar 3 - Commission
Engine).  Mirrors the budgetScenario.py style: JWT on every route,
Exceptions.register_not_found on 404, filters as query params, skip/limit.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import CommissionRate, CommissionRateCreate, CommissionRateUpdate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/", response_model=List[CommissionRate])
def get_commission_rates(
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
    """List commission rates with optional filters."""
    return crud.get_commission_rates(
        db, id_line=id_line, active_only=active_only, date_ref=date,
        skip=skip, limit=limit,
    )


@router.get("/{id_commission_rate}", response_model=CommissionRate)
def get_commission_rate_by_id(
    id_commission_rate: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a commission rate by its ID."""
    db_rate = crud.get_commission_rate_by_id(db, id_commission_rate)
    if db_rate is None:
        Exceptions.register_not_found("CommissionRate", id_commission_rate)
    return db_rate


@router.post("/", response_model=CommissionRate)
def create_commission_rate(
    commission_rate: CommissionRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a rate. Validates BR-12 (period) / BR-13 (overlap) -> 400 (E-CR-1/E-CR-2)."""
    if commission_rate.id_line is not None:
        line_obj = crud.get_line_by_id(db, commission_rate.id_line)
        if line_obj is None:
            Exceptions.register_not_found("Line", commission_rate.id_line)
    return crud.create_commission_rate(db, commission_rate)


@router.put("/{id_commission_rate}", response_model=CommissionRate)
def update_commission_rate(
    id_commission_rate: int,
    commission_rate: CommissionRateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update (merge non-None fields) + same validations; overlap check
    excludes the row itself."""
    if commission_rate.id_line is not None:
        line_obj = crud.get_line_by_id(db, commission_rate.id_line)
        if line_obj is None:
            Exceptions.register_not_found("Line", commission_rate.id_line)
    db_rate = crud.update_commission_rate(db, id_commission_rate, commission_rate)
    if db_rate is None:
        Exceptions.register_not_found("CommissionRate", id_commission_rate)
    return db_rate


@router.delete("/{id_commission_rate}")
def delete_commission_rate(
    id_commission_rate: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete (audit-friendly deactivation: PUT is_active=false)."""
    db_rate = crud.delete_commission_rate(db, id_commission_rate)
    if db_rate is None:
        Exceptions.register_not_found("CommissionRate", id_commission_rate)
    return {"message": "Commission rate deleted successfully"}
