"""
AccountPayable CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import AccountPayable as AccountPayableModel
from app.schemas.budget import AccountPayableCreate


def create_account_payable(
    db: Session, account_payable: AccountPayableCreate
) -> AccountPayableModel:
    """Create a new account payable record."""
    db_ap = AccountPayableModel(
        **account_payable.model_dump(),
        balance=account_payable.total_amount,
    )
    db.add(db_ap)
    db.commit()
    db.refresh(db_ap)
    return db_ap


def get_account_payable_by_id(
    db: Session, id_account_payable: int
) -> Optional[AccountPayableModel]:
    """Get an account payable by its ID."""
    return db.query(AccountPayableModel).filter(
        AccountPayableModel.id_account_payable == id_account_payable
    ).first()


def get_accounts_payable(
    db: Session,
    id_cost_center: Optional[int] = None,
    status: Optional[str] = None,
    due_date_le: Optional[date] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[AccountPayableModel]:
    """Get accounts payable with optional filters."""
    query = db.query(AccountPayableModel)
    if id_cost_center is not None:
        query = query.filter(AccountPayableModel.id_cost_center == id_cost_center)
    if status is not None:
        query = query.filter(AccountPayableModel.status == status)
    if due_date_le is not None:
        query = query.filter(AccountPayableModel.due_date <= due_date_le)
    return query.order_by(
        AccountPayableModel.due_date
    ).offset(skip).limit(limit).all()


def update_account_payable(
    db: Session, id_account_payable: int, account_payable: AccountPayableCreate
) -> Optional[AccountPayableModel]:
    """Update an existing account payable."""
    db_ap = db.query(AccountPayableModel).filter(
        AccountPayableModel.id_account_payable == id_account_payable
    ).first()
    if db_ap:
        update_data = account_payable.model_dump()
        if "balance" not in update_data or update_data["balance"] is None:
            update_data["balance"] = update_data["total_amount"]
        for key, value in update_data.items():
            setattr(db_ap, key, value)
        db.commit()
        db.refresh(db_ap)
    return db_ap


def delete_account_payable(db: Session, id_account_payable: int) -> bool:
    """Delete an account payable by ID."""
    db_ap = db.query(AccountPayableModel).filter(
        AccountPayableModel.id_account_payable == id_account_payable
    ).first()
    if db_ap:
        db.delete(db_ap)
        db.commit()
        return True
    return False
