"""
UploadStatus CRUD Operations
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.budget import ActualCost as ActualCostModel
from app.models.budget import ActualExpense as ActualExpenseModel
from app.models.budget import PaymentLedger as PaymentLedgerModel
from app.models.budget import AccountReceivable as AccountReceivableModel


def get_upload_status(db: Session) -> dict:
    """MAX(created_at) por dataset ETL. None si la tabla esta vacia."""
    return {
        "actual_costs": {"last_upload": db.query(func.max(ActualCostModel.created_at)).scalar()},
        "actual_expenses": {"last_upload": db.query(func.max(ActualExpenseModel.created_at)).scalar()},
        "payment_ledger": {"last_upload": db.query(func.max(PaymentLedgerModel.created_at)).scalar()},
        "accounts_receivable": {"last_upload": db.query(func.max(AccountReceivableModel.created_at)).scalar()},
    }
