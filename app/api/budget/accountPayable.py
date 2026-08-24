"""
Account Payable API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import AccountPayable, AccountPayableCreate, AccountPayableFull
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_account_payable}", response_model=AccountPayableFull)
def get_account_payable_by_id(
    id_account_payable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an account payable by its ID with its ledger entries."""
    db_ap = crud.get_account_payable_by_id(db, id_account_payable)
    if db_ap is None:
        Exceptions.register_not_found("AccountPayable", id_account_payable)
    return db_ap


@router.get("/", response_model=List[AccountPayable])
def get_accounts_payable(
    id_cost_center: Optional[int] = None,
    status: Optional[str] = None,
    due_date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get accounts payable with optional filters.

    Parameters:
    - id_cost_center: Optional[int] - filter by cost center
    - status: Optional[str] - filter by status (open, partial, paid)
    - due_date_le: Optional[date] - filter by due date (less than or equal)
    - skip: int (default: 0)
    - limit: int (default: 50)
    """
    return crud.get_accounts_payable(
        db, id_cost_center=id_cost_center, status=status,
        due_date_le=due_date_le, skip=skip, limit=limit,
    )


@router.post("/", response_model=AccountPayable)
def create_account_payable(
    account_payable: AccountPayableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new account payable record."""
    return crud.create_account_payable(db, account_payable)


@router.put("/{id_account_payable}", response_model=AccountPayable)
def update_account_payable(
    id_account_payable: int,
    account_payable: AccountPayableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing account payable."""
    db_ap = crud.update_account_payable(db, id_account_payable, account_payable)
    if db_ap is None:
        Exceptions.register_not_found("AccountPayable", id_account_payable)
    return db_ap


@router.delete("/{id_account_payable}")
def delete_account_payable(
    id_account_payable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an account payable by ID."""
    success = crud.delete_account_payable(db, id_account_payable)
    if not success:
        Exceptions.register_not_found("AccountPayable", id_account_payable)
    return {"message": "Account payable deleted successfully"}
