"""
LineInternmentTerm CRUD Operations (BE-S9-INTERNMENT-SPLIT,
backend.02_19 §5.2)

EXACT mirror of crud/budget/linePayableTerm.py (flat catalog, legacy
``db.query(Model).filter(...)`` style with ``db: Session`` first, T-03;
no ORM joins; auto-created table, zero manual DDL — NFR-BE9-5). The only
difference is the BASE those pcts multiply: internment cost vs supplier
cost (models/budget/lineInternmentTerm.py docstring).

Ordering contract (D-7 mirror, spec §5.2): ``payment_days asc`` with
``id_line_internment_term asc`` tie-break, so the installment list starts
at the oldest cash date. BE-S9 consumes that order in the derived
carryover rows (crud.get_carryover_purchase_lines / backend.02_19 §4)
and FE-S10 in the live Vista Flujo; installments are NEVER materialized
(NFR-BE9-1).

404s are raised by the API layer: ``update``/``delete`` return ``None``
when the row is missing (Optional->None convention of
crud/budget/linePayableTerm.py).
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import LineInternmentTerm as LineInternmentTermModel
from app.schemas.budget import LineInternmentTermCreate


def get_line_internment_terms(
    db: Session,
) -> List[LineInternmentTermModel]:
    """Full catalog for the FE terms screen (spec §5.3: GET / returns it
    all, no pagination — the catalog is one row per installment of a few
    Lines, R-S5-3 mirror).

    Order: id_line, payment_days, id (grouped and chronological)."""
    return db.query(LineInternmentTermModel).order_by(
        LineInternmentTermModel.id_line,
        LineInternmentTermModel.payment_days,
        LineInternmentTermModel.id_line_internment_term,
    ).all()


def get_line_internment_terms_by_line(
    db: Session, id_line: int
) -> List[LineInternmentTermModel]:
    """Terms of ONE line in the deterministic installment order
    ``payment_days asc, id_line_internment_term asc`` (§4 / D-7). ``[]``
    when the line has no terms — NOT a 404 (spec §5.3; the derivation
    then answers the single 100 % row at the anchor, BR-INT-04)."""
    return db.query(LineInternmentTermModel).filter(
        LineInternmentTermModel.id_line == id_line
    ).order_by(
        LineInternmentTermModel.payment_days,
        LineInternmentTermModel.id_line_internment_term,
    ).all()


def get_line_internment_term_by_id(
    db: Session, id_line_internment_term: int
) -> Optional[LineInternmentTermModel]:
    """Get one internment term by its ID (None when missing -> 404 in API)."""
    return db.query(LineInternmentTermModel).filter(
        LineInternmentTermModel.id_line_internment_term
        == id_line_internment_term
    ).first()


def create_line_internment_term(
    db: Session, payload: LineInternmentTermCreate
) -> LineInternmentTermModel:
    """Create a term. The id_line FK existence check (404
    "Line {id_line} not found", spec §5.3) is resolved by the API layer
    before calling, mirroring create_line_payable_term's flow."""
    db_term = LineInternmentTermModel(**payload.model_dump())
    db.add(db_term)
    db.commit()
    db.refresh(db_term)
    return db_term


def update_line_internment_term(
    db: Session,
    id_line_internment_term: int,
    payload: LineInternmentTermCreate,
) -> Optional[LineInternmentTermModel]:
    """Full replacement of the mutable fields (id_line, payment_pct,
    payment_days) — PUT is idempotent and the schema requires them all
    (spec §3.2 has no partial Update model). Returns None when the row is
    missing (404 at the API layer)."""
    db_term = get_line_internment_term_by_id(db, id_line_internment_term)
    if db_term is None:
        return None
    for key, value in payload.model_dump().items():
        setattr(db_term, key, value)
    db.commit()
    db.refresh(db_term)
    return db_term


def delete_line_internment_term(
    db: Session, id_line_internment_term: int
) -> Optional[LineInternmentTermModel]:
    """Physical delete (catalog rows carry no history; under §4 deleting
    the LAST internment terms of a Line simply switches the FUTURE
    purchase derivation to the single-100 % row at the anchor
    (BR-INT-04, D-S7-4 mirror) — derived rows are recomputed per request
    and the installments are never materialized, so there is nothing to
    clean up). Returns the deleted row or None when missing -> 404 at the
    API layer."""
    db_term = get_line_internment_term_by_id(db, id_line_internment_term)
    if db_term is None:
        return None
    db.delete(db_term)
    db.commit()
    return db_term
