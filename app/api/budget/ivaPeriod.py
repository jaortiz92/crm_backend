"""
Iva Period API Endpoints (BE-S10-IVA)

CRUD of the yearly IVA settlement calendar (spec backend.02_20 §5.8),
mounted at /budget/iva-period by the budget aggregator
(line-internment-rate pattern; app/main.py does NOT change — the budget
aggregator was already mounted, §5.9).

Mirrors app/api/budget/lineInternmentRate.py exactly on: JWT dependency
stack (get_db + get_current_user on every route, NO role gate — same
catalog level as every other satellite, NFR-BE10-6), Optional->None
CRUD results resolved to 404/400 in THIS layer, and the EXACT §5.8
error literals, which AC-BE10-5 quotes verbatim and therefore win over
the generic Exceptions.register_not_found wording: 404 "IvaPeriod {id}
not found" and 400 "Period {period_no} already exists for year
{period_year}" (the POST duplicate and the PUT re-parent collision
share the literal; re-saving a row onto its own (year, no) is
idempotent and never collides with itself).

GET / accepts the OPTIONAL ?year= filter (§5.8) and answers the rows
ordered (period_year, period_no); an empty year answers [] (a year
without calendar is a LEGAL state — settlement then degrades to the
unassigned bucket + literal warning, §4.4/AC-BE10-6, never a 404).
Validation 422s come from the schemas (period_year [2000, 2100],
period_no [1, 36], date_to >= date_from via model_validator).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.schemas import (
    User, IvaPeriod, IvaPeriodCreate,
)
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud

router = APIRouter()


def _ensure_no_period_conflict(
    db: Session, period_year: int, period_no: int
) -> None:
    """PUT re-parent guard (spec §5.8): the target (year, ordinal) is
    owned by ANOTHER row -> 400 with the exact literal the POST
    duplicate uses."""
    if crud.get_iva_period_by_year_no(db, period_year, period_no) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Period {period_no} already exists for year {period_year}"
            ),
        )


@router.get("/", response_model=List[IvaPeriod])
def get_iva_periods(
    year: Optional[int] = Query(
        None, ge=2000, le=2100,
        description="Filter the calendar by fiscal year (all years when "
                    "omitted; order period_year, period_no)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Calendar rows, optionally of ONE year (spec §5.8: GET /?year=;
    no pagination — N periods per year at most, R-S5-3 mirror)."""
    return crud.get_iva_periods(db, year=year)


@router.post("/", response_model=IvaPeriod,
             status_code=status.HTTP_201_CREATED)
def create_iva_period(
    iva_period: IvaPeriodCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create ONE period of a year's calendar. 422 on the schema ranges
    (period_year ∉ [2000, 2100], period_no ∉ [1, 36] or date_to <
    date_from — AC-BE10-5); 400 "Period {period_no} already exists for
    year {period_year}" when the year already owns that ordinal — the
    CRUD create returns None on the duplicate (spec §5.3) and it is
    resolved to that literal here (AC-BE10-5), BEFORE the unique
    constraint could raise. Ranges are NOT cross-validated against the
    other periods (§3.2): gaps/overlaps degrade in the §4.4 first-cover
    rule."""
    db_period = crud.create_iva_period(db, iva_period)
    if db_period is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Period {iva_period.period_no} already exists for year "
                f"{iva_period.period_year}"
            ),
        )
    return db_period


@router.put("/{id_iva_period}", response_model=IvaPeriod)
def update_iva_period(
    id_iva_period: int,
    iva_period: IvaPeriodCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the fields of the period (full-replacement PUT; every
    mutable field is required, no partial Update model — §5.3). 404
    "IvaPeriod {id} not found" when the row is missing; 400 "Period
    {period_no} already exists for year {period_year}" when RE-PARENTING
    to a (year, no) owned by ANOTHER row (re-saving the row's own pair
    is idempotent and never collides with itself); 422 on ranges/range
    sanity."""
    db_period = crud.get_iva_period_by_id(db, id_iva_period)
    if db_period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IvaPeriod {id_iva_period} not found",
        )
    if (db_period.period_year, db_period.period_no) != (
        iva_period.period_year, iva_period.period_no
    ):
        # Only a RE-PARENT can collide (the row itself is excluded by
        # the inequality above), same guard flow as the rate catalog.
        _ensure_no_period_conflict(
            db, iva_period.period_year, iva_period.period_no
        )
    return crud.update_iva_period(db, id_iva_period, iva_period)


@router.delete("/{id_iva_period}")
def delete_iva_period(
    id_iva_period: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physical delete of a period (calendar rows carry no history;
    every settlement recomputes from the periods present at READ TIME,
    so the events of a deleted period simply flow to the next covering
    period or the unassigned bucket — nothing materialized to clean up,
    NFR-BE10-1). Response: the deleted id (same shape as the term/rate
    DELETEs). 404 "IvaPeriod {id} not found"."""
    db_period = crud.delete_iva_period(db, id_iva_period)
    if db_period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IvaPeriod {id_iva_period} not found",
        )
    return {"deleted_id": id_iva_period}
