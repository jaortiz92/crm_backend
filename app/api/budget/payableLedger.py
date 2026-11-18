"""
Payable Ledger API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import PayableLedger, PayableLedgerCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_payable_ledger}", response_model=PayableLedger)
def get_payable_ledger_by_id(
    id_payable_ledger: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a payable ledger record by its ID."""
    db_ledger = crud.get_payable_ledger_by_id(db, id_payable_ledger)
    if db_ledger is None:
        Exceptions.register_not_found("PayableLedger", id_payable_ledger)
    return db_ledger


@router.get("/", response_model=List[PayableLedger])
def get_payable_ledger(
    id_account_payable: Optional[int] = None,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get payable ledger records with optional filters."""
    return crud.get_payable_ledger(
        db, id_account_payable=id_account_payable,
        date_ge=date_ge, date_le=date_le,
        skip=skip, limit=limit,
    )


@router.get(
    "/account-payable/{id_account_payable}",
    response_model=List[PayableLedger],
)
def get_ledger_by_account_payable(
    id_account_payable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all ledger entries for a given account payable."""
    return crud.get_ledger_by_account_payable(db, id_account_payable)


@router.post("/", response_model=PayableLedger)
def create_payable_ledger(
    payable_ledger: PayableLedgerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new payable ledger record.
    Validates that amount_paid does not exceed the outstanding balance.
    Automatically updates the parent account payable balance and status.
    """
    return crud.create_payable_ledger(db, payable_ledger)


@router.delete("/{id_payable_ledger}")
def delete_payable_ledger(
    id_payable_ledger: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a payable ledger record by ID."""
    success = crud.delete_payable_ledger(db, id_payable_ledger)
    if not success:
        Exceptions.register_not_found("PayableLedger", id_payable_ledger)
    return {"message": "Payable ledger record deleted successfully"}
