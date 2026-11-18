"""
LineCostRate CRUD Operations

Master catalog of budgeted COGS % per product line (Pilar 1 - P&L).
Validations BR-12 (inverted validity) and BR-13 (active overlap) are
enforced here; SQL CHECK/UNIQUE constraints are intentionally not used
(see spec 02_09 §4.1).
"""

from datetime import date
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.budget import LineCostRate as LineCostRateModel
from app.schemas.budget import LineCostRateCreate, LineCostRateUpdate


def get_line_cost_rates(
    db: Session,
    id_line: Optional[int] = None,
    active_only: bool = False,
    date_ref: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[LineCostRateModel]:
    """List rates with optional filters.

    - id_line: rates of a concrete line (use None for the global group via
      the API only if needed; plain equality keeps the global rows out).
    - active_only: restrict to is_active rows.
    - date_ref: only rates in force at that date, applying §4.4.1
      (is_active AND date_from <= date_ref <= date_to).
    """
    query = db.query(LineCostRateModel)
    if id_line is not None:
        query = query.filter(LineCostRateModel.id_line == id_line)
    if active_only:
        query = query.filter(LineCostRateModel.is_active.is_(True))
    if date_ref is not None:
        query = query.filter(
            LineCostRateModel.is_active.is_(True),
            LineCostRateModel.date_from <= date_ref,
            LineCostRateModel.date_to >= date_ref,
        )
    return query.order_by(
        LineCostRateModel.id_line_cost_rate
    ).offset(skip).limit(limit).all()


def get_line_cost_rate_by_id(
    db: Session, id_line_cost_rate: int
) -> Optional[LineCostRateModel]:
    """Get a line cost rate by its ID."""
    return db.query(LineCostRateModel).filter(
        LineCostRateModel.id_line_cost_rate == id_line_cost_rate
    ).first()


def _rate_period_invalid(date_from: date, date_to: date) -> bool:
    """BR-12: validity range inverted (date_from > date_to)."""
    return date_to < date_from


def _rate_overlaps(
    db: Session,
    id_line: Optional[int],
    date_from: date,
    date_to: date,
    exclude_id: Optional[int] = None,
) -> bool:
    """BR-13: another ACTIVE rate of the same group overlaps [date_from, date_to].

    The global group (id_line IS NULL) is compared NULL-safe with .is_(None).
    Only is_active rows count; on update the row itself is excluded.
    """
    query = db.query(LineCostRateModel).filter(
        LineCostRateModel.date_from <= date_to,
        LineCostRateModel.date_to >= date_from,
        LineCostRateModel.is_active.is_(True),
    )
    if id_line is None:
        query = query.filter(LineCostRateModel.id_line.is_(None))
    else:
        query = query.filter(LineCostRateModel.id_line == id_line)
    if exclude_id is not None:
        query = query.filter(
            LineCostRateModel.id_line_cost_rate != exclude_id
        )
    return query.first() is not None


def create_line_cost_rate(
    db: Session, payload: LineCostRateCreate
) -> LineCostRateModel:
    """Create a line cost rate (validates BR-12/BR-13: E-4/E-5 -> 400)."""
    if _rate_period_invalid(payload.date_from, payload.date_to):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be on or after date_from",
        )
    if _rate_overlaps(
        db, payload.id_line, payload.date_from, payload.date_to
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Overlapping active rate for this line (or global) period; "
                "deactivate or adjust dates first"
            ),
        )
    db_rate = LineCostRateModel(**payload.model_dump())
    db.add(db_rate)
    db.commit()
    db.refresh(db_rate)
    return db_rate


def update_line_cost_rate(
    db: Session, id_line_cost_rate: int, payload: LineCostRateUpdate
) -> Optional[LineCostRateModel]:
    """Update a line cost rate with partial merge (only non-None fields).

    Re-runs the same validations on the merged values, excluding the row
    itself from the overlap check (BR-12/BR-13 -> E-4/E-5). Returns None if
    the rate does not exist (404 is resolved by the API layer).
    """
    db_rate = get_line_cost_rate_by_id(db, id_line_cost_rate)
    if db_rate is None:
        return None

    merged = payload.model_dump(exclude_none=True)
    eff_id_line = merged.get("id_line", db_rate.id_line)
    eff_date_from = merged.get("date_from", db_rate.date_from)
    eff_date_to = merged.get("date_to", db_rate.date_to)
    eff_is_active = merged.get("is_active", db_rate.is_active)

    if _rate_period_invalid(eff_date_from, eff_date_to):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be on or after date_from",
        )
    # Overlap only matters while the resulting row would be active (BR-13).
    if eff_is_active and _rate_overlaps(
        db, eff_id_line, eff_date_from, eff_date_to,
        exclude_id=db_rate.id_line_cost_rate,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Overlapping active rate for this line (or global) period; "
                "deactivate or adjust dates first"
            ),
        )

    for key, value in merged.items():
        setattr(db_rate, key, value)
    db.commit()
    db.refresh(db_rate)
    return db_rate


def delete_line_cost_rate(
    db: Session, id_line_cost_rate: int
) -> Optional[LineCostRateModel]:
    """Physically delete a rate. Returns the deleted row or None if missing.

    Audit-friendly deactivation is done with PUT is_active=False (§6.2).
    """
    db_rate = get_line_cost_rate_by_id(db, id_line_cost_rate)
    if db_rate is None:
        return None
    db.delete(db_rate)
    db.commit()
    return db_rate
