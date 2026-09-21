"""
Line Internment Term API Endpoints (BE-S9-INTERNMENT-SPLIT)

CRUD of the internment-payment-terms catalog (spec backend.02_19 §5.3),
mounted at /budget/line-internment-term by the budget aggregator
(line-payable-term pattern; main.py already includes `budget`).

Mirrors app/api/budget/linePayableTerm.py exactly on: JWT dependency
stack (get_db + get_current_user on every route, no role gate),
Optional->None CRUD results resolved to 404 in this layer, and FK
pre-checks before create/update. Error DETAIL literals follow spec §5.3
/ AC-BE9-2 verbatim ("Line {id_line} not found",
"LineInternmentTerm {id} not found"), which is the BE-S4D planning
convention (f"{Entity} {id} not found"), not the generic
Exceptions.register_not_found wording — the acceptance criteria quote the
exact strings, so they win over the helper formatting.

GET /by-line/{id_line} answers [] for lines without terms (and even for
unknown lines): absence of terms is NOT an error (spec §5.3; the §4
derivation then emits the single 100 % row at the anchor, BR-INT-04)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import User, LineInternmentTerm, LineInternmentTermCreate
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud

router = APIRouter()


def _ensure_line_exists(db: Session, id_line: int) -> None:
    """POST/PUT FK guard (spec §5.3): unknown Line -> 404 with the exact
    literal "Line {id_line} not found" (not the generic helper wording).
    Mirrors the linePayableTerm.py create/update pre-check flow."""
    line_obj = crud.get_line_by_id(db, id_line)
    if line_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Line {id_line} not found",
        )


@router.get("/", response_model=List[LineInternmentTerm])
def get_line_internment_terms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full internment-terms catalog ordered id_line, payment_days (spec
    §5.3; no pagination — flat, small master catalog, R-S5-3 mirror)."""
    return crud.get_line_internment_terms(db)


@router.get("/by-line/{id_line}", response_model=List[LineInternmentTerm])
def get_line_internment_terms_by_line(
    id_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Terms of ONE line in installment order (payment_days asc, id asc —
    D-7). [] when the line has none — NOT a 404 (spec §5.3)."""
    return crud.get_line_internment_terms_by_line(db, id_line)


@router.post("/", response_model=LineInternmentTerm,
             status_code=status.HTTP_201_CREATED)
def create_line_internment_term(
    line_internment_term: LineInternmentTermCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a term. 422 when payment_pct ∉ (0, 1] or payment_days is
    not an integer (Field validators,
    schemas/budget/lineInternmentTerm.py); 404 "Line {id_line} not found"
    when the Line does not exist (§5.3)."""
    _ensure_line_exists(db, line_internment_term.id_line)
    return crud.create_line_internment_term(db, line_internment_term)


@router.put("/{id_line_internment_term}", response_model=LineInternmentTerm)
def update_line_internment_term(
    id_line_internment_term: int,
    line_internment_term: LineInternmentTermCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the fields of one term (full-replacement PUT; every mutable
    field is required). 404 "LineInternmentTerm {id} not found" when
    missing; 404 "Line {id_line} not found" when re-parenting to an
    unknown Line (same guard as POST, mirroring linePayableTerm's PUT);
    422 on range."""
    _ensure_line_exists(db, line_internment_term.id_line)
    db_term = crud.update_line_internment_term(
        db, id_line_internment_term, line_internment_term
    )
    if db_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LineInternmentTerm {id_line_internment_term} not found",
        )
    return db_term


@router.delete("/{id_line_internment_term}")
def delete_line_internment_term(
    id_line_internment_term: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete of one term (the future derivation of the Line is
    recomputed per request — deleting the last terms switches it to the
    single 100 % row at the anchor, BR-INT-04; nothing is materialized to
    clean up, NFR-BE9-1). Response: the deleted id (same shape the
    payable-term DELETE uses). 404 "LineInternmentTerm {id} not found"."""
    db_term = crud.delete_line_internment_term(db, id_line_internment_term)
    if db_term is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LineInternmentTerm {id_line_internment_term} not found",
        )
    return {"deleted_id": id_line_internment_term}
