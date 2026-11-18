"""
CostCenter CRUD Operations
"""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.budget import CostCenter as CostCenterModel
from app.schemas.budget import CostCenterCreate


def create_cost_center(db: Session, cost_center: CostCenterCreate) -> CostCenterModel:
    """Create a new cost center."""
    db_cost_center = CostCenterModel(**cost_center.model_dump())
    db.add(db_cost_center)
    db.commit()
    db.refresh(db_cost_center)
    return db_cost_center


def get_cost_center_by_id(db: Session, id_cost_center: int) -> Optional[CostCenterModel]:
    """Get a cost center by its ID."""
    return db.query(CostCenterModel).filter(
        CostCenterModel.id_cost_center == id_cost_center
    ).first()


def get_cost_center_by_code(db: Session, cost_center_code: str) -> Optional[CostCenterModel]:
    """Get a cost center by its unique code."""
    return db.query(CostCenterModel).filter(
        CostCenterModel.cost_center_code == cost_center_code
    ).first()


def get_cost_centers(
    db: Session, skip: int = 0, limit: int = 50, is_active: Optional[bool] = None
) -> List[CostCenterModel]:
    """Get all cost centers with optional active filter."""
    query = db.query(CostCenterModel)
    if is_active is not None:
        query = query.filter(CostCenterModel.is_active == is_active)
    return query.order_by(CostCenterModel.cost_center_code).offset(skip).limit(limit).all()


def update_cost_center(
    db: Session, id_cost_center: int, cost_center: CostCenterCreate
) -> Optional[CostCenterModel]:
    """Update an existing cost center."""
    db_cost_center = db.query(CostCenterModel).filter(
        CostCenterModel.id_cost_center == id_cost_center
    ).first()
    if db_cost_center:
        for key, value in cost_center.model_dump().items():
            setattr(db_cost_center, key, value)
        db.commit()
        db.refresh(db_cost_center)
    return db_cost_center


def delete_cost_center(db: Session, id_cost_center: int) -> bool:
    """Delete a cost center by ID."""
    db_cost_center = db.query(CostCenterModel).filter(
        CostCenterModel.id_cost_center == id_cost_center
    ).first()
    if db_cost_center:
        db.delete(db_cost_center)
        db.commit()
        return True
    return False
