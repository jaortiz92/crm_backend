"""
Account Receivable API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import AccountReceivable, AccountReceivableCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_account_receivable}", response_model=AccountReceivable)
def get_account_receivable_by_id(
    id_account_receivable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get an account receivable by its ID."""
    db_ar = crud.get_account_receivable_by_id(db, id_account_receivable)
    if db_ar is None:
        Exceptions.register_not_found("AccountReceivable", id_account_receivable)
    return db_ar


@router.get("/", response_model=List[AccountReceivable])
def get_accounts_receivable(
    id_customer: Optional[int] = None,
    status: Optional[str] = None,
    due_date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get accounts receivable with optional filters.

    Parameters:
    - id_customer: Optional[int] - filter by customer
    - status: Optional[str] - filter by status (open, partial, paid, overdue)
    - due_date_le: Optional[date] - filter by due date (less than or equal)
    - skip: int (default: 0)
    - limit: int (default: 50)
    """
    return crud.get_accounts_receivable(
        db, id_customer=id_customer, status=status,
        due_date_le=due_date_le, skip=skip, limit=limit,
    )


@router.post("/", response_model=AccountReceivable)
def create_account_receivable(
    account_receivable: AccountReceivableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new account receivable record."""
    return crud.create_account_receivable(db, account_receivable)


@router.put("/{id_account_receivable}", response_model=AccountReceivable)
def update_account_receivable(
    id_account_receivable: int,
    account_receivable: AccountReceivableCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing account receivable."""
    db_ar = crud.update_account_receivable(db, id_account_receivable, account_receivable)
    if db_ar is None:
        Exceptions.register_not_found("AccountReceivable", id_account_receivable)
    return db_ar


@router.delete("/{id_account_receivable}")
def delete_account_receivable(
    id_account_receivable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an account receivable by ID."""
    success = crud.delete_account_receivable(db, id_account_receivable)
    if not success:
        Exceptions.register_not_found("AccountReceivable", id_account_receivable)
    return {"message": "Account receivable deleted successfully"}
