"""Company financing-credit API; never shares the invoice-credit domain."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import get_db
from app.api.utils import Exceptions
from app.core.auth import get_current_user
import app.crud as crud
from app.schemas import (
    FinancingCreditCreate, FinancingCreditUpdate, FinancingCreditDetail,
    FinancingCreditOut, FinancingCreditListResponse, FinancingInstallmentOut,
    FinancingSchedulePreview, FinancingRecalculateResult,
    FinancingCloseRequest, FinancingCloseResult,
    FinancingCreditDeleteResult,
)
from app.services.budget.financingCreditService import (
    close_financing_credit, create_financing_credit, preview_financing_credit,
    delete_financing_credit, recalculate_financing_credit, serialize_credit,
    update_financing_credit,
)


router = APIRouter()


def _commit_or_rollback(db: Session, operation):
    try:
        result = operation()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.get("", response_model=FinancingCreditListResponse)
def list_financing_credits(
    q: Optional[str] = None,
    id_cost_center: Optional[int] = Query(None, gt=0),
    status: Optional[str] = Query(None, pattern="^(active|closed)$"),
    origin_type: Optional[str] = Query(None, pattern="^(new|legacy)$"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    total, credits = crud.list_financing_credits(
        db, q, id_cost_center, status, origin_type, page, size,
    )
    return {"total": total, "items": [serialize_credit(db, credit) for credit in credits]}


# The literal route must precede /{id_financing_credit}, since its segment
# otherwise parses as an integer path parameter in the legacy budget router.
@router.post("/preview", response_model=FinancingSchedulePreview)
def preview_financing_credit_endpoint(
    payload: FinancingCreditCreate,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    return preview_financing_credit(db, payload)


@router.post("", response_model=FinancingCreditDetail, status_code=201)
def create_financing_credit_endpoint(
    payload: FinancingCreditCreate,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    credit, generation = _commit_or_rollback(
        db, lambda: create_financing_credit(db, payload),
    )
    result = serialize_credit(db, credit, include_installments=True)
    result["warnings"] = generation["warnings"]
    return result


@router.get("/{id_financing_credit}/schedule", response_model=list[FinancingInstallmentOut])
def get_financing_credit_schedule(
    id_financing_credit: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=360),
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    credit = crud.get_financing_credit(db, id_financing_credit)
    if credit is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail={"message": "date_from must be <= date_to"})
    return crud.get_installments(db, credit, date_from, date_to, offset, limit)


@router.get("/{id_financing_credit}", response_model=FinancingCreditDetail)
def get_financing_credit_detail(
    id_financing_credit: int,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    credit = crud.get_financing_credit(db, id_financing_credit)
    if credit is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    return serialize_credit(db, credit, include_installments=True)


@router.delete(
    "/{id_financing_credit}",
    response_model=FinancingCreditDeleteResult,
)
def delete_financing_credit_endpoint(
    id_financing_credit: int,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    return _commit_or_rollback(
        db, lambda: delete_financing_credit(db, id_financing_credit),
    )


@router.put("/{id_financing_credit}")
def update_financing_credit_endpoint(
    id_financing_credit: int,
    payload: FinancingCreditUpdate,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    credit, generation = _commit_or_rollback(
        db,
        lambda: update_financing_credit(
            db, id_financing_credit, payload.model_dump(exclude_unset=True),
        ),
    )
    return {"credit": serialize_credit(db, credit, include_installments=True), **generation}


@router.post("/{id_financing_credit}/recalculate", response_model=FinancingRecalculateResult)
def recalculate_financing_credit_endpoint(
    id_financing_credit: int,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    generation = _commit_or_rollback(
        db, lambda: recalculate_financing_credit(db, id_financing_credit),
    )
    return {"id_financing_credit": id_financing_credit, **generation}


@router.post("/{id_financing_credit}/close", response_model=FinancingCloseResult)
def close_financing_credit_endpoint(
    id_financing_credit: int,
    payload: FinancingCloseRequest,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    credit, suspended = _commit_or_rollback(
        db,
        lambda: close_financing_credit(
            db, id_financing_credit, payload.cutoff_date, payload.remaining_balance,
        ),
    )
    return {
        "id_financing_credit": credit.id_financing_credit,
        "status": "closed",
        "suspended_installments": suspended,
        "message": "Closed with explicitly reported zero balance; no payment was recorded.",
    }
