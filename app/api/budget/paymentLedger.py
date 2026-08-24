"""
Payment Ledger API Endpoints
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import PaymentLedger, PaymentLedgerCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

router = APIRouter()


@router.get("/{id_payment_ledger}", response_model=PaymentLedger)
def get_payment_ledger_by_id(
    id_payment_ledger: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a payment ledger record by its ID."""
    db_payment = crud.get_payment_ledger_by_id(db, id_payment_ledger)
    if db_payment is None:
        Exceptions.register_not_found("PaymentLedger", id_payment_ledger)
    return db_payment


@router.get("/", response_model=List[PaymentLedger])
def get_payment_ledger(
    id_account_receivable: Optional[int] = None,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get payment ledger records with optional filters."""
    return crud.get_payment_ledger(
        db, id_account_receivable=id_account_receivable,
        date_ge=date_ge, date_le=date_le,
        skip=skip, limit=limit,
    )


@router.get(
    "/account-receivable/{id_account_receivable}",
    response_model=List[PaymentLedger],
)
def get_payments_by_account_receivable(
    id_account_receivable: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all payments for a given account receivable."""
    return crud.get_payments_by_account_receivable(db, id_account_receivable)


@router.post("/", response_model=PaymentLedger)
def create_payment_ledger(
    payment_ledger: PaymentLedgerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new payment ledger record."""
    ar = crud.get_account_receivable_by_id(db, payment_ledger.id_account_receivable)
    if ar is None:
        Exceptions.register_not_found(
            "AccountReceivable", payment_ledger.id_account_receivable
        )
    if payment_ledger.id_invoice is not None:
        inv = crud.get_invoice_by_id(db, payment_ledger.id_invoice)
        if inv is None:
            Exceptions.register_not_found("Invoice", payment_ledger.id_invoice)
    return crud.create_payment_ledger(db, payment_ledger)


@router.put("/{id_payment_ledger}", response_model=PaymentLedger)
def update_payment_ledger(
    id_payment_ledger: int,
    payment_ledger: PaymentLedgerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing payment ledger record."""
    db_payment = crud.update_payment_ledger(db, id_payment_ledger, payment_ledger)
    if db_payment is None:
        Exceptions.register_not_found("PaymentLedger", id_payment_ledger)
    return db_payment


@router.delete("/{id_payment_ledger}")
def delete_payment_ledger(
    id_payment_ledger: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a payment ledger record by ID."""
    success = crud.delete_payment_ledger(db, id_payment_ledger)
    if not success:
        Exceptions.register_not_found("PaymentLedger", id_payment_ledger)
    return {"message": "Payment ledger record deleted successfully"}
