"""
PaymentLedger CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import PaymentLedger as PaymentLedgerModel
from app.schemas.budget import PaymentLedgerCreate


def create_payment_ledger(
    db: Session, payment_ledger: PaymentLedgerCreate
) -> PaymentLedgerModel:
    """Create a new payment ledger record."""
    db_payment = PaymentLedgerModel(**payment_ledger.model_dump())
    db.add(db_payment)
    db.commit()
    db.refresh(db_payment)
    return db_payment


def create_payment_ledger_bulk(
    db: Session, payment_ledgers: List[PaymentLedgerCreate]
) -> List[PaymentLedgerModel]:
    """Bulk insert payment ledger records from ETL."""
    db_records = [PaymentLedgerModel(**pl.model_dump()) for pl in payment_ledgers]
    db.bulk_save_objects(db_records)
    db.commit()
    return db_records


def get_payment_ledger_by_id(
    db: Session, id_payment_ledger: int
) -> Optional[PaymentLedgerModel]:
    """Get a payment ledger record by its ID."""
    return db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.id_payment_ledger == id_payment_ledger
    ).first()


def get_payments_by_account_receivable(
    db: Session, id_account_receivable: int
) -> List[PaymentLedgerModel]:
    """Get all payments for a given account receivable."""
    return db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.id_account_receivable == id_account_receivable
    ).order_by(PaymentLedgerModel.payment_date.desc()).all()


def get_payment_ledger(
    db: Session,
    id_account_receivable: Optional[int] = None,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[PaymentLedgerModel]:
    """Get payment ledger records with optional filters."""
    query = db.query(PaymentLedgerModel)
    if id_account_receivable is not None:
        query = query.filter(PaymentLedgerModel.id_account_receivable == id_account_receivable)
    if date_ge is not None:
        query = query.filter(PaymentLedgerModel.payment_date >= date_ge)
    if date_le is not None:
        query = query.filter(PaymentLedgerModel.payment_date <= date_le)
    return query.order_by(
        PaymentLedgerModel.payment_date.desc()
    ).offset(skip).limit(limit).all()


def update_payment_ledger(
    db: Session, id_payment_ledger: int, payment_ledger: PaymentLedgerCreate
) -> Optional[PaymentLedgerModel]:
    """Update an existing payment ledger record."""
    db_payment = db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.id_payment_ledger == id_payment_ledger
    ).first()
    if db_payment:
        for key, value in payment_ledger.model_dump().items():
            setattr(db_payment, key, value)
        db.commit()
        db.refresh(db_payment)
    return db_payment


def delete_payment_ledger(db: Session, id_payment_ledger: int) -> bool:
    """Delete a payment ledger record by ID."""
    db_payment = db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.id_payment_ledger == id_payment_ledger
    ).first()
    if db_payment:
        db.delete(db_payment)
        db.commit()
        return True
    return False
