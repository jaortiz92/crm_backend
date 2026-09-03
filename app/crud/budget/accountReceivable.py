"""
AccountReceivable CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import AccountReceivable as AccountReceivableModel
from app.models.budget import PaymentLedger as PaymentLedgerModel
from app.models.budget.accountReceivable import ReceivableStatusEnum
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


def nullify_payment_ledger_refs_for(
    db: Session, id_accounts_receivable: List[int]
) -> int:
    """Liberar punteros payment_ledger.id_account_receivable (FK sin ondelete).
    NO hace commit - el caller controla la transacción."""
    if not id_accounts_receivable:
        return 0
    return db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.id_account_receivable.in_(id_accounts_receivable)
    ).update(
        {PaymentLedgerModel.id_account_receivable: None},
        synchronize_session=False,
    )


def delete_accounts_receivable_by_documents(
    db: Session, document_numbers: List[str]
) -> int:
    """Eliminar registros por lista de document_numbers (reemplazo atómico ETL,
    fase C2). Nullifica el ledger afectado antes del DELETE.
    NO hace commit - el caller controla la transacción.
    Retorna filas borradas (no documentos)."""
    if not document_numbers:
        return 0
    ids = [
        row.id_account_receivable
        for row in db.query(AccountReceivableModel.id_account_receivable).filter(
            AccountReceivableModel.document_number.in_(document_numbers)
        ).all()
    ]
    nullify_payment_ledger_refs_for(db, ids)
    return db.query(AccountReceivableModel).filter(
        AccountReceivableModel.document_number.in_(document_numbers)
    ).delete(synchronize_session=False)


def close_accounts_receivable_not_in(
    db: Session, document_numbers: List[str]
) -> int:
    """Cierre por marcaje (D-2): documentos OPEN ausentes del archivo pasan a
    PAID con el saldo consumido (paid_amount = balance, balance = 0).
    NO toca PAID/PARTIAL ni aging_bucket/statement_date (auditoría).
    NO hace commit - el caller controla la transacción."""
    if not document_numbers:
        # Evita NOT IN () inválido; el ETL nunca llega aquí con archivo vacío.
        return 0
    return db.query(AccountReceivableModel).filter(
        AccountReceivableModel.status == ReceivableStatusEnum.OPEN,
        AccountReceivableModel.document_number.notin_(document_numbers),
    ).update(
        {
            AccountReceivableModel.status: ReceivableStatusEnum.PAID,
            AccountReceivableModel.paid_amount: AccountReceivableModel.balance,
            AccountReceivableModel.balance: 0,
        },
        synchronize_session=False,
    )


def delete_accounts_receivable_by_document(
    db: Session, document_number: str
) -> int:
    """Eliminar todos los registros con un document_number exacto
    (case-sensitive). Nullifica el ledger antes (misma transacción)."""
    ids = [
        row.id_account_receivable
        for row in db.query(AccountReceivableModel.id_account_receivable).filter(
            AccountReceivableModel.document_number == document_number
        ).all()
    ]
    nullify_payment_ledger_refs_for(db, ids)
    count = db.query(AccountReceivableModel).filter(
        AccountReceivableModel.document_number == document_number
    ).delete(synchronize_session=False)
    db.commit()
    return count
