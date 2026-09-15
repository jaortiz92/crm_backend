"""
Line Payable Term API Endpoints (BE-S5-PAYABLE-TERMS)

CRUD of the supplier payment terms catalog (spec backend.02_15 §5),
mounted at /budget/line-payable-term by the budget aggregator
(line-cost-rate pattern; main.py already includes `budget`).

Mirrors app/api/budget/lineCostRate.py exactly on: JWT dependency stack
(get_db + get_current_user on every route, no role gate), Optional->None
CRUD results resolved to 404 in this layer, and FK pre-checks before
create/update. Error DETAIL literals follow spec §5 / AC-S5-BE-8 verbatim
("Line {id_line} not found", "LinePayableTerm {id} not found"), which is
the BE-S4D planning convention (f"{Entity} {id} not found"), not the
generic Exceptions.register_not_found wording — the acceptance criteria
quote the exact strings, so they win over the helper formatting.

GET /by-line/{id_line} answers [] for lines without terms (and even for
unknown lines): absence of terms is NOT an error (spec §5)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import User, LinePayableTerm, LinePayableTermCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud

router = APIRouter()


def _ensure_line_exists(db: Session, id_line: int) -> None:
    """POST/PUT FK guard (spec §5): unknown Line -> 404 with the exact
    literal "Line {id_line} not found" (not the generic helper wording).
    Mirrors the lineCostRate.py create/update pre-check flow."""
    line_obj = crud.get_line_by_id(db, id_line)
    if line_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Line {id_line} not found",
        )


@router.get("/", response_model=List[LinePayableTerm])
def get_line_payable_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full payable-terms catalog ordered id_line, payment_days (spec §5;
    no pagination — flat, small master catalog, R-S5-3)."""
    return crud.get_line_payable_terms(db)


@router.get("/by-line/{id_line}", response_model=List[LinePayableTerm])
def get_line_payable_terms_by_line(
    id_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Terms of ONE line in installment order (payment_days asc, id asc —
    D-7). [] when the line has none — NOT a 404 (spec §5)."""
    return crud.get_line_payable_terms_by_line(db, id_line)


@router.post("/", response_model=LinePayableTerm,
             status_code=status.HTTP_201_CREATED)
def create_line_payable_term(
    line_payable_term: LinePayableTermCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a term. 422 when payment_pct ∉ (0, 1] or payment_days is not
    an integer (Field validators, schemas/budget/linePayableTerm.py);
    404 "Line {id_line} not found" when the Line does not exist (§5)."""
    _ensure_line_exists(db, line_payable_term.id_line)
    return crud.create_line_payable_term(db, line_payable_term)


@router.put("/{id_line_payable_term}", response_model=LinePayableTerm)
def update_line_payable_term(
    id_line_payable_term: int,
    line_payable_term: LinePayableTermCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the fields of one term (full-replacement PUT; every mutable
    field is required). 404 "LinePayableTerm {id} not found" when missing;
    404 "Line {id_line} not found" when re-parenting to an unknown Line
    (same guard as POST, mirroring lineCostRate's PUT); 422 on range."""
    _ensure_line_exists(db, line_payable_term.id_line)
    db_term = crud.update_line_payable_term(
        db, id_line_payable_term, line_payable_term
    )
    if db_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LinePayableTerm {id_line_payable_term} not found",
        )
    return db_term


@router.delete("/{id_line_payable_term}")
def delete_line_payable_term(
    id_line_payable_term: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete of one term (already-materialized installments are
    untouched — BR-TERM-07). Response: the deleted id (same shape the
    BE-S4D line DELETE uses). 404 "LinePayableTerm {id} not found"."""
    db_term = crud.delete_line_payable_term(db, id_line_payable_term)
    if db_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LinePayableTerm {id_line_payable_term} not found",
        )
    return {"deleted_id": id_line_payable_term}
