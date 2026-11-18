"""Query-style CRUD helpers for company financing schedules."""

from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.budget import (
    BudgetLine, FinancingCredit, FinancingCreditInstallment,
)


def get_financing_credit(db: Session, id_financing_credit: int, lock: bool = False):
    query = db.query(FinancingCredit).filter(
        FinancingCredit.id_financing_credit == id_financing_credit
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def list_financing_credits(
    db: Session, q: Optional[str] = None, id_cost_center: Optional[int] = None,
    status: Optional[str] = None, origin_type: Optional[str] = None,
    page: int = 1, size: int = 50,
):
    query = db.query(FinancingCredit)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            FinancingCredit.name.ilike(pattern)
            | FinancingCredit.lender_name.ilike(pattern)
        )
    if id_cost_center is not None:
        query = query.filter(FinancingCredit.id_cost_center == id_cost_center)
    if status is not None:
        query = query.filter(FinancingCredit.status == status)
    if origin_type is not None:
        query = query.filter(FinancingCredit.origin_type == origin_type)
    total = query.count()
    items = (query.order_by(FinancingCredit.id_financing_credit)
             .offset((page - 1) * size).limit(size).all())
    return total, items


def get_active_installments(db: Session, credit: FinancingCredit):
    if credit.status != "active":
        return []
    return db.query(FinancingCreditInstallment).filter(
        FinancingCreditInstallment.id_financing_credit == credit.id_financing_credit,
        FinancingCreditInstallment.schedule_revision == credit.schedule_revision,
    ).order_by(FinancingCreditInstallment.installment_number).all()


def get_installments(
    db: Session, credit: FinancingCredit, date_from: Optional[date] = None,
    date_to: Optional[date] = None, offset: int = 0, limit: int = 360,
):
    if credit.status != "active":
        return []
    query = db.query(FinancingCreditInstallment).filter(
        FinancingCreditInstallment.id_financing_credit == credit.id_financing_credit,
        FinancingCreditInstallment.schedule_revision == credit.schedule_revision,
    )
    if date_from is not None:
        query = query.filter(FinancingCreditInstallment.period_end >= date_from)
    if date_to is not None:
        query = query.filter(FinancingCreditInstallment.period_end <= date_to)
    return (query.order_by(FinancingCreditInstallment.installment_number)
            .offset(offset).limit(limit).all())


def delete_financing_credit(db: Session, id_financing_credit: int):
    """Delete one financing credit and only its owned projections.

    The caller owns the transaction. Budget lines are flushed away before
    installments, and only exact financing-engine IDs belonging to any
    revision of this credit are eligible for deletion.
    """
    credit = get_financing_credit(db, id_financing_credit, lock=True)
    if credit is None:
        return None

    installments = (db.query(FinancingCreditInstallment).filter(
        FinancingCreditInstallment.id_financing_credit == id_financing_credit,
    ).with_for_update().all())
    installment_ids = [
        row.id_financing_credit_installment for row in installments
    ]

    budget_lines = []
    if installment_ids:
        budget_lines = (db.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(installment_ids),
        ).all())
    for line in budget_lines:
        db.delete(line)
    db.flush()

    for installment in installments:
        db.delete(installment)
    db.delete(credit)
    db.flush()
    return {
        "id_financing_credit": credit.id_financing_credit,
        "budget_lines": len(budget_lines),
        "installments": len(installments),
    }
