"""
Line Internment Rate API Endpoints (BE-S9-INTERNMENT-SPLIT)

CRUD of the internment-rate catalog (spec backend.02_19 §5.3), mounted
at /budget/line-internment-rate by the budget aggregator
(line-payable-term pattern; main.py already includes `budget`).

Mirrors app/api/budget/linePayableTerm.py exactly on: JWT dependency
stack (get_db + get_current_user on every route, no role gate),
Optional->None CRUD results resolved to 404/400 in this layer, and FK
pre-checks before create/update. Error DETAIL literals follow spec §5.3
/ AC-BE9-1 verbatim ("Line {id_line} not found",
"LineInternmentRate {id} not found",
"Line {id_line} already has an internment rate"), which is the BE-S4D
planning convention (f"{Entity} {id} not found"), not the generic
Exceptions.register_not_found wording — the acceptance criteria quote the
exact strings, so they win over the helper formatting.

Per-Line uniqueness (spec §3.1/§5.1): the CRUD ``create`` answers None
when the Line already has a rate and THIS layer resolves it into the
friendly 400 BEFORE the ``unique=True`` index could raise an
IntegrityError (the index still guards races); the PUT re-parent
collision uses the same literal.

GET /by-line/{id_line} answers 200 with null for lines without a rate:
absence of a rate means pct = 0 (§4/A-5) and is NOT an error (spec §5.3).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import (
    User, LineInternmentRate, LineInternmentRateCreate,
)
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


def _ensure_no_rate_conflict(db: Session, id_line: int) -> None:
    """PUT re-parent guard (spec §5.3): the target Line already has
    ANOTHER rate -> 400 with the same literal the POST duplicate uses."""
    if crud.get_line_internment_rate_by_line(db, id_line) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Line {id_line} already has an internment rate",
        )


@router.get("/", response_model=List[LineInternmentRate])
def get_line_internment_rates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full internment-rates catalog ordered id_line (spec §5.3; no
    pagination — flat, small master catalog, at most one row per Line)."""
    return crud.get_line_internment_rates(db)


@router.get("/by-line/{id_line}", response_model=Optional[LineInternmentRate])
def get_line_internment_rate_by_line(
    id_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rate of ONE line, or plain 200 null when the line has none —
    absence = pct 0 (zero internment rows, §4/A-5): NOT a 404, not even
    for unknown lines (spec §5.3)."""
    return crud.get_line_internment_rate_by_line(db, id_line)


@router.post("/", response_model=LineInternmentRate,
             status_code=status.HTTP_201_CREATED)
def create_line_internment_rate(
    line_internment_rate: LineInternmentRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create the rate of a Line. 422 when internment_pct ∉ (0, 1]
    (Field validators, schemas/budget/lineInternmentRate.py); 404
    "Line {id_line} not found" when the Line does not exist (§5.3); 400
    "Line {id_line} already has an internment rate" when the Line already
    has one — the CRUD create returns None on the duplicate (spec §5.1)
    and it is resolved to that literal here, AC-BE9-1."""
    _ensure_line_exists(db, line_internment_rate.id_line)
    db_rate = crud.create_line_internment_rate(db, line_internment_rate)
    if db_rate is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Line {line_internment_rate.id_line} already has an "
                "internment rate"
            ),
        )
    return db_rate


@router.put("/{id_line_internment_rate}", response_model=LineInternmentRate)
def update_line_internment_rate(
    id_line_internment_rate: int,
    line_internment_rate: LineInternmentRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the fields of the rate (full-replacement PUT; every mutable
    field is required). 404 "Line {id_line} not found" when the target
    Line does not exist (same guard as POST, mirroring linePayableTerm's
    PUT); 404 "LineInternmentRate {id} not found" when the row is missing;
    400 "Line {id_line} already has an internment rate" when RE-PARENTING
    to a Line that already has another rate (re-saving the row's own
    id_line is idempotent and never collides with itself); 422 on
    range."""
    _ensure_line_exists(db, line_internment_rate.id_line)
    db_rate = crud.get_line_internment_rate_by_id(
        db, id_line_internment_rate
    )
    if db_rate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LineInternmentRate {id_line_internment_rate} not found",
        )
    if db_rate.id_line != line_internment_rate.id_line:
        # Only a RE-PARENT can collide (the row itself is excluded by the
        # id_line inequality above).
        _ensure_no_rate_conflict(db, line_internment_rate.id_line)
    return crud.update_line_internment_rate(
        db, id_line_internment_rate, line_internment_rate
    )


@router.delete("/{id_line_internment_rate}")
def delete_line_internment_rate(
    id_line_internment_rate: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete of the rate of a Line (future derivations fall
    back to pct = 0 — zero internment rows, §4/A-5; nothing is
    materialized to clean up, NFR-BE9-1). Response: the deleted id (same
    shape as the term DELETE). 404 "LineInternmentRate {id} not found"."""
    db_rate = crud.delete_line_internment_rate(db, id_line_internment_rate)
    if db_rate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LineInternmentRate {id_line_internment_rate} not found",
        )
    return {"deleted_id": id_line_internment_rate}
