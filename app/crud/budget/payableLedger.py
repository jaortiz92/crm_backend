"""
PayableLedger CRUD Operations
"""

from datetime import date
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.budget import (
    AccountPayable as AccountPayableModel,
    PayableLedger as PayableLedgerModel,
)
from app.schemas.budget import PayableLedgerCreate


def create_payable_ledger(
    db: Session, payable_ledger: PayableLedgerCreate
) -> PayableLedgerModel:
    """
    Create a new payable ledger record.
    Validates that amount_paid does not exceed the current balance.
    Updates the parent account payable balance and status automatically.
    """
    db_ap = db.query(AccountPayableModel).filter(
        AccountPayableModel.id_account_payable == payable_ledger.id_account_payable
    ).first()
    if db_ap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AccountPayable with id '{payable_ledger.id_account_payable}' does not exist",
        )
    if payable_ledger.amount_paid > db_ap.balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Payment amount ({payable_ledger.amount_paid}) "
                f"exceeds outstanding balance ({db_ap.balance})"
            ),
        )

    db_ledger = PayableLedgerModel(**payable_ledger.model_dump())
    db.add(db_ledger)

    db_ap.balance = round(db_ap.balance - payable_ledger.amount_paid, 2)
    if db_ap.balance == 0:
        db_ap.status = "paid"
    else:
        db_ap.status = "partial"

    db.commit()
    db.refresh(db_ledger)
    db.refresh(db_ap)
    return db_ledger


def get_payable_ledger_by_id(
    db: Session, id_payable_ledger: int
) -> Optional[PayableLedgerModel]:
    """Get a payable ledger record by its ID."""
    return db.query(PayableLedgerModel).filter(
        PayableLedgerModel.id_payable_ledger == id_payable_ledger
    ).first()


def get_ledger_by_account_payable(
    db: Session, id_account_payable: int
) -> List[PayableLedgerModel]:
    """Get all ledger entries for a given account payable."""
    return db.query(PayableLedgerModel).filter(
        PayableLedgerModel.id_account_payable == id_account_payable
    ).order_by(PayableLedgerModel.payment_date.desc()).all()


def get_payable_ledger(
    db: Session,
    id_account_payable: Optional[int] = None,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[PayableLedgerModel]:
    """Get payable ledger records with optional filters."""
    query = db.query(PayableLedgerModel)
    if id_account_payable is not None:
        query = query.filter(PayableLedgerModel.id_account_payable == id_account_payable)
    if date_ge is not None:
        query = query.filter(PayableLedgerModel.payment_date >= date_ge)
    if date_le is not None:
        query = query.filter(PayableLedgerModel.payment_date <= date_le)
    return query.order_by(
        PayableLedgerModel.payment_date.desc()
    ).offset(skip).limit(limit).all()


def delete_payable_ledger(db: Session, id_payable_ledger: int) -> bool:
    """Delete a payable ledger record by ID."""
    db_ledger = db.query(PayableLedgerModel).filter(
        PayableLedgerModel.id_payable_ledger == id_payable_ledger
    ).first()
    if db_ledger:
        db.delete(db_ledger)
        db.commit()
        return True
    return False
