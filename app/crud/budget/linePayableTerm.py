"""
LinePayableTerm CRUD Operations (BE-S5-PAYABLE-TERMS; catalog
re-semantized by BE-S7-COGS-PAYFLOW, backend.02_17 §2 — these terms now
describe how the supplier of a Line's COGS gets PAID; endpoints/callers
below adapted, no other code change)

Legacy ``db.query(Model).filter(...)`` style with ``db: Session`` first
(spec backend.02_15 §5; mirrors crud/linePaymentRule.py, the collections
counterpart that must NOT be reused — D-1). Flat catalog, no ORM joins.

Ordering contract (spec §6, D-7): ``payment_days asc`` with
``id_line_payable_term asc`` tie-break, so the installment list starts at
the oldest cash date. BE-S7 consumes that order in the derived carryover
rows (crud.get_carryover_cogs_lines / backend.02_17 §4) and FE-S7 in the
live Vista Flujo; the BE-S5 materialization helper that also used it was
rolled back (backend.02_17 §2).

404s are raised by the API layer: ``update``/``delete`` return ``None``
when the row is missing (Optional->None convention of
crud/budget/lineCostRate.py and update_budget_line_cell).
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import LinePayableTerm as LinePayableTermModel
from app.schemas.budget import LinePayableTermCreate


def get_line_payable_terms(
    db: Session,
) -> List[LinePayableTermModel]:
    """Full catalog for the FE terms screen (spec §5: GET / returns it all,
    no pagination — the catalog is one row per installment of a few Lines,
    R-S5-3: "el catálogo es pocas filas").

    Order: id_line, payment_days, id (grouped and chronological)."""
    return db.query(LinePayableTermModel).order_by(
        LinePayableTermModel.id_line,
        LinePayableTermModel.payment_days,
        LinePayableTermModel.id_line_payable_term,
    ).all()


def get_line_payable_terms_by_line(
    db: Session, id_line: int
) -> List[LinePayableTermModel]:
    """Terms of ONE line in the deterministic installment order
    ``payment_days asc, id_line_payable_term asc`` (§6 / D-7). ``[]`` when
    the line has no terms — NOT a 404 (spec §5)."""
    return db.query(LinePayableTermModel).filter(
        LinePayableTermModel.id_line == id_line
    ).order_by(
        LinePayableTermModel.payment_days,
        LinePayableTermModel.id_line_payable_term,
    ).all()


def get_line_payable_term_by_id(
    db: Session, id_line_payable_term: int
) -> Optional[LinePayableTermModel]:
    """Get one payable term by its ID (None when missing -> 404 in API)."""
    return db.query(LinePayableTermModel).filter(
        LinePayableTermModel.id_line_payable_term == id_line_payable_term
    ).first()


def create_line_payable_term(
    db: Session, payload: LinePayableTermCreate
) -> LinePayableTermModel:
    """Create a payable term. The id_line FK existence check (404
    "Line {id_line} not found", spec §5) is resolved by the API layer
    before calling, mirroring create_line_cost_rate's flow."""
    db_term = LinePayableTermModel(**payload.model_dump())
    db.add(db_term)
    db.commit()
    db.refresh(db_term)
    return db_term


def update_line_payable_term(
    db: Session,
    id_line_payable_term: int,
    payload: LinePayableTermCreate,
) -> Optional[LinePayableTermModel]:
    """Full replacement of the mutable fields (id_line, payment_pct,
    payment_days) — PUT is idempotent and the schema requires them all
    (spec §3.1 has no partial Update model). Returns None when the row is
    missing (404 at the API layer)."""
    db_term = get_line_payable_term_by_id(db, id_line_payable_term)
    if db_term is None:
        return None
    for key, value in payload.model_dump().items():
        setattr(db_term, key, value)
    db.commit()
    db.refresh(db_term)
    return db_term


def delete_line_payable_term(
    db: Session, id_line_payable_term: int
) -> Optional[LinePayableTermModel]:
    """Physical delete (catalog rows carry no history; under BE-S7 §2/§4
    deleting the terms of a Line simply switches the FUTURE COGS payment
    derivation to the D-S7-4 single-100 % behavior — derived rows are
    recomputed per request and cost is never materialized, so there is
    nothing to clean up). Returns the deleted row or None when missing ->
    404 at the API layer."""
    db_term = get_line_payable_term_by_id(db, id_line_payable_term)
    if db_term is None:
        return None
    db.delete(db_term)
    db.commit()
    return db_term
