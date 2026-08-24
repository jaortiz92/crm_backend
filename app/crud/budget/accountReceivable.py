"""
AccountReceivable CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import AccountReceivable as AccountReceivableModel
from app.schemas.budget import AccountReceivableCreate


def create_account_receivable(
    db: Session, account_receivable: AccountReceivableCreate
) -> AccountReceivableModel:
    """Create a new account receivable record."""
    db_ar = AccountReceivableModel(**account_receivable.model_dump())
    db.add(db_ar)
    db.commit()
    db.refresh(db_ar)
    return db_ar


def create_accounts_receivable_bulk(
    db: Session, accounts_receivable: List[AccountReceivableCreate]
) -> List[AccountReceivableModel]:
    """Bulk insert account receivable records from ETL."""
    db_records = [AccountReceivableModel(**ar.model_dump()) for ar in accounts_receivable]
    db.bulk_save_objects(db_records)
    db.commit()
    return db_records


def get_account_receivable_by_id(
    db: Session, id_account_receivable: int
) -> Optional[AccountReceivableModel]:
    """Get an account receivable by its ID."""
    return db.query(AccountReceivableModel).filter(
        AccountReceivableModel.id_account_receivable == id_account_receivable
    ).first()


def get_accounts_receivable(
    db: Session,
    id_customer: Optional[int] = None,
    status: Optional[str] = None,
    due_date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[AccountReceivableModel]:
    """Get accounts receivable with optional filters."""
    query = db.query(AccountReceivableModel)
    if id_customer is not None:
        query = query.filter(AccountReceivableModel.id_customer == id_customer)
    if status is not None:
        query = query.filter(AccountReceivableModel.status == status)
    if due_date_le is not None:
        query = query.filter(AccountReceivableModel.due_date <= due_date_le)
    return query.order_by(
        AccountReceivableModel.due_date
    ).offset(skip).limit(limit).all()


def update_account_receivable(
    db: Session, id_account_receivable: int, account_receivable: AccountReceivableCreate
) -> Optional[AccountReceivableModel]:
    """Update an existing account receivable."""
    db_ar = db.query(AccountReceivableModel).filter(
        AccountReceivableModel.id_account_receivable == id_account_receivable
    ).first()
    if db_ar:
        for key, value in account_receivable.model_dump().items():
            setattr(db_ar, key, value)
        db.commit()
        db.refresh(db_ar)
    return db_ar


def delete_account_receivable(db: Session, id_account_receivable: int) -> bool:
    """Delete an account receivable by ID."""
    db_ar = db.query(AccountReceivableModel).filter(
        AccountReceivableModel.id_account_receivable == id_account_receivable
    ).first()
    if db_ar:
        db.delete(db_ar)
        db.commit()
        return True
    return False
