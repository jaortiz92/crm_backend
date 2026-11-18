"""
LineInternmentRate CRUD Operations (BE-S9-INTERNMENT-SPLIT,
backend.02_19 §5.1)

Legacy ``db.query(Model).filter(...)`` style with ``db: Session`` first
(T-03; mirrors crud/budget/linePayableTerm.py). Flat catalog, no ORM
joins. Auto-created table, zero manual DDL (NFR-BE9-5).

Uniqueness per Line (spec §3.1): ``create`` checks the Line first and
returns ``None`` when it already has a rate — the API layer resolves
that into the friendly 400 "Line {id_line} already has an internment
rate" BEFORE the ``unique=True`` IntegrityError would surface (the index
still guards races, but the useful message is produced here).

404s are raised by the API layer: ``update``/``delete`` return ``None``
when the row is missing (Optional->None convention of
crud/budget/linePayableTerm.py). Physical delete (the catalog carries no
history): under §4 a deleted rate degrades every purchase of the Line
to pct = 0 — zero internment rows, byte-identical single supplier
stream (A-5/NFR-BE9-3). Single commit per mutation (T-05).
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import LineInternmentRate as LineInternmentRateModel
from app.schemas.budget import LineInternmentRateCreate


def get_line_internment_rates(
    db: Session,
) -> List[LineInternmentRateModel]:
    """Full catalog for the FE rates screen (spec §5.3: GET / returns it
    all, no pagination — at most one row per Line, R-S5-3 mirror).

    Order: id_line (grouped by Line)."""
    return db.query(LineInternmentRateModel).order_by(
        LineInternmentRateModel.id_line,
    ).all()


def get_line_internment_rate_by_line(
    db: Session, id_line: int
) -> Optional[LineInternmentRateModel]:
    """Rate of ONE line (None when the line has none — the §4 derivation
    reads that as pct = 0 and the API answers 200 null, the absence is
    NOT a 404, spec §5.3). The unique index makes first() deterministic."""
    return db.query(LineInternmentRateModel).filter(
        LineInternmentRateModel.id_line == id_line
    ).first()


def get_line_internment_rate_by_id(
    db: Session, id_line_internment_rate: int
) -> Optional[LineInternmentRateModel]:
    """Get one rate by its ID (None when missing -> 404 in API)."""
    return db.query(LineInternmentRateModel).filter(
        LineInternmentRateModel.id_line_internment_rate
        == id_line_internment_rate
    ).first()


def create_line_internment_rate(
    db: Session, payload: LineInternmentRateCreate
) -> Optional[LineInternmentRateModel]:
    """Create the rate of a Line, or return ``None`` when the Line ALREADY
    has one (spec §5.1: the duplicate is resolved to a 400 by the API
    layer before the unique index could raise). The id_line FK existence
    check (404 "Line {id_line} not found") is resolved by the API layer
    before calling, mirroring create_line_payable_term's flow."""
    if get_line_internment_rate_by_line(db, payload.id_line) is not None:
        return None
    db_rate = LineInternmentRateModel(**payload.model_dump())
    db.add(db_rate)
    db.commit()
    db.refresh(db_rate)
    return db_rate


def update_line_internment_rate(
    db: Session,
    id_line_internment_rate: int,
    payload: LineInternmentRateCreate,
) -> Optional[LineInternmentRateModel]:
    """Full replacement of the mutable fields (id_line, internment_pct) —
    PUT is idempotent and the schema requires them all (spec §3.1 has no
    partial Update model). Returns None when the row is missing (404 at
    the API layer); the re-parent collision (payload.id_line owned by
    another rate) is resolved to a 400 by the API layer BEFORE calling."""
    db_rate = get_line_internment_rate_by_id(db, id_line_internment_rate)
    if db_rate is None:
        return None
    for key, value in payload.model_dump().items():
        setattr(db_rate, key, value)
    db.commit()
    db.refresh(db_rate)
    return db_rate


def delete_line_internment_rate(
    db: Session, id_line_internment_rate: int
) -> Optional[LineInternmentRateModel]:
    """Physical delete (catalog rows carry no history; deleting the rate
    of a Line simply switches the FUTURE purchase derivation to pct = 0 —
    zero internment rows and the supplier stream back on the full amount,
    §4/A-5 — because installments are recomputed per request and never
    materialized, there is nothing to clean up). Returns the deleted row
    or None when missing -> 404 at the API layer."""
    db_rate = get_line_internment_rate_by_id(db, id_line_internment_rate)
    if db_rate is None:
        return None
    db.delete(db_rate)
    db.commit()
    return db_rate
