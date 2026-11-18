"""
IvaPeriod CRUD Operations (BE-S10-IVA, backend.02_20 §5.3)

Legacy ``db.query(Model).filter(...)`` style with ``db: Session`` first
(T-03), EXACT mirror of crud/budget/lineInternmentRate.py: flat yearly
calendar, no ORM joins, auto-created table, zero manual DDL
(NFR-BE10-5).

Uniqueness per (period_year, period_no) (spec §3.2): ``create`` checks
the pair first and returns ``None`` when the year already owns that
ordinal — the API layer resolves that into the friendly 400 "Period
{period_no} already exists for year {period_year}" BEFORE the unique
constraint could surface an IntegrityError (the index still guards
races, but the useful message is produced here). 404s are raised by the
API layer: ``update``/``delete`` return ``None`` when the row is missing
(Optional->None convention). PUT is a full replacement with the SAME
duplicate guard on re-parent, resolved by the API before calling.

Ranges are never validated nor overlap-repaired here (§3.2): the §4.4
first-cover rule degrades gaps (unassigned bucket) and overlaps
deterministically. Physical delete (the calendar carries no history):
removing a period row simply re-routes the NEXT settlement read — past
liquidations are pure derivations, nothing is materialized to clean up
(NFR-BE10-1). T-05: a single commit per mutation.
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import IvaPeriod as IvaPeriodModel
from app.schemas.budget import IvaPeriodCreate


def get_iva_periods(
    db: Session, year: Optional[int] = None,
) -> List[IvaPeriodModel]:
    """Calendar rows, optionally filtered by fiscal year (spec §5.8
    GET /?year=; at most N rows per year — no pagination, R-S5-3 mirror).

    Order: (period_year, period_no) — §5.3."""
    query = db.query(IvaPeriodModel)
    if year is not None:
        query = query.filter(IvaPeriodModel.period_year == year)
    return query.order_by(
        IvaPeriodModel.period_year,
        IvaPeriodModel.period_no,
    ).all()


def get_iva_period_by_id(
    db: Session, id_iva_period: int
) -> Optional[IvaPeriodModel]:
    """Get one period by its ID (None when missing -> 404 in API)."""
    return db.query(IvaPeriodModel).filter(
        IvaPeriodModel.id_iva_period == id_iva_period
    ).first()


def get_iva_period_by_year_no(
    db: Session, period_year: int, period_no: int
) -> Optional[IvaPeriodModel]:
    """Row owning (year, ordinal) — the unique constraint makes first()
    deterministic. The §4.4 derivation and the API duplicate guards share
    it; absence is NOT an error (a year without calendar settles to the
    unassigned bucket + literal warning, §4.4/AC-BE10-6)."""
    return db.query(IvaPeriodModel).filter(
        IvaPeriodModel.period_year == period_year,
        IvaPeriodModel.period_no == period_no,
    ).first()


def create_iva_period(
    db: Session, payload: IvaPeriodCreate
) -> Optional[IvaPeriodModel]:
    """Create a period of the year, or return ``None`` when (year, no)
    ALREADY exists (spec §5.3: the duplicate is resolved to a 400 by the
    API layer before the unique index could raise)."""
    if get_iva_period_by_year_no(db, payload.period_year,
                                 payload.period_no) is not None:
        return None
    db_period = IvaPeriodModel(**payload.model_dump())
    db.add(db_period)
    db.commit()
    db.refresh(db_period)
    return db_period


def update_iva_period(
    db: Session,
    id_iva_period: int,
    payload: IvaPeriodCreate,
) -> Optional[IvaPeriodModel]:
    """Full replacement of the mutable fields (period_year, period_no,
    dates, description) — PUT is idempotent and the schema requires them
    all (no partial Update model, spec §5.3). Returns None when the row
    is missing (404 at the API layer); the re-parent collision (payload
    (year, no) owned by ANOTHER row) is resolved to a 400 by the API
    layer BEFORE calling, exactly like the rate catalog."""
    db_period = get_iva_period_by_id(db, id_iva_period)
    if db_period is None:
        return None
    for key, value in payload.model_dump().items():
        setattr(db_period, key, value)
    db.commit()
    db.refresh(db_period)
    return db_period


def delete_iva_period(
    db: Session, id_iva_period: int
) -> Optional[IvaPeriodModel]:
    """Physical delete (calendar rows carry no history; every settlement
    is recomputed live from the periods present AT READ TIME, so deleting
    a row simply moves its future events to the next covering period or
    the unassigned bucket — nothing materialized to clean up,
    NFR-BE10-1). Returns the deleted row or None when missing -> 404 at
    the API layer."""
    db_period = get_iva_period_by_id(db, id_iva_period)
    if db_period is None:
        return None
    db.delete(db_period)
    db.commit()
    return db_period
