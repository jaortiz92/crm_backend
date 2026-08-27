"""
ActualCost CRUD Operations
"""

from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import ActualCost as ActualCostModel
from app.schemas.budget import ActualCostCreate


def create_actual_cost(db: Session, actual_cost: ActualCostCreate) -> ActualCostModel:
    """Create a new actual cost record."""
    db_actual_cost = ActualCostModel(**actual_cost.model_dump())
    db.add(db_actual_cost)
    db.commit()
    db.refresh(db_actual_cost)
    return db_actual_cost


def create_actual_costs_bulk(
    db: Session, actual_costs: List[ActualCostCreate]
) -> List[ActualCostModel]:
    """Bulk insert actual cost records from ETL."""
    db_costs = [ActualCostModel(**c.model_dump()) for c in actual_costs]
    db.bulk_save_objects(db_costs)
    db.commit()
    return db_costs


def get_actual_cost_by_id(
    db: Session, id_actual_cost: int
) -> Optional[ActualCostModel]:
    """Get an actual cost by its ID."""
    return db.query(ActualCostModel).filter(
        ActualCostModel.id_actual_cost == id_actual_cost
    ).first()


def get_actual_costs_by_cost_center(
    db: Session, id_cost_center: int, skip: int = 0, limit: int = 50
) -> List[ActualCostModel]:
    """Get actual costs filtered by cost center."""
    return db.query(ActualCostModel).filter(
        ActualCostModel.id_cost_center == id_cost_center
    ).order_by(ActualCostModel.cost_date.desc()).offset(skip).limit(limit).all()


def get_actual_costs(
    db: Session,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    id_cost_center: Optional[int] = None,
    cost_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[ActualCostModel]:
    """Get actual costs with optional filters."""
    query = db.query(ActualCostModel)
    if date_ge is not None:
        query = query.filter(ActualCostModel.cost_date >= date_ge)
    if date_le is not None:
        query = query.filter(ActualCostModel.cost_date <= date_le)
    if id_cost_center is not None:
        query = query.filter(ActualCostModel.id_cost_center == id_cost_center)
    if cost_type is not None:
        query = query.filter(ActualCostModel.cost_type == cost_type)
    return query.order_by(ActualCostModel.cost_date.desc()).offset(skip).limit(limit).all()


def update_actual_cost(
    db: Session, id_actual_cost: int, actual_cost: ActualCostCreate
) -> Optional[ActualCostModel]:
    """Update an existing actual cost."""
    db_actual_cost = db.query(ActualCostModel).filter(
        ActualCostModel.id_actual_cost == id_actual_cost
    ).first()
    if db_actual_cost:
        for key, value in actual_cost.model_dump().items():
            setattr(db_actual_cost, key, value)
        db.commit()
        db.refresh(db_actual_cost)
    return db_actual_cost


def delete_actual_cost(db: Session, id_actual_cost: int) -> bool:
    """Delete an actual cost by ID."""
    db_actual_cost = db.query(ActualCostModel).filter(
        ActualCostModel.id_actual_cost == id_actual_cost
    ).first()
    if db_actual_cost:
        db.delete(db_actual_cost)
        db.commit()
        return True
    return False

def delete_actual_costs_by_document(db: Session, document_number: str) -> int:
    """Delete all actual cost records with the given document_number.
    Returns the number of records deleted."""
    deleted_count = db.query(ActualCostModel).filter(
        ActualCostModel.document_number == document_number
    ).delete(synchronize_session=False)
    db.commit()
    return deleted_count
