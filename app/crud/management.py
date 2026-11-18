from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.management import Management as ManagementModel
from app.schemas.management import ManagementCreate


def create_management(db: Session, management: ManagementCreate) -> ManagementModel:
    db_management = ManagementModel(**management.model_dump())
    db.add(db_management)
    db.commit()
    db.refresh(db_management)
    return db_management


def get_management_by_id(db: Session, id_management: int) -> Optional[ManagementModel]:
    return db.query(ManagementModel).filter(
        ManagementModel.id_management == id_management
    ).first()


def get_management_by_code(db: Session, management_code: str) -> Optional[ManagementModel]:
    return db.query(ManagementModel).filter(
        ManagementModel.management_code == management_code
    ).first()


def get_managements(db: Session, skip: int = 0, limit: int = 50) -> List[ManagementModel]:
    return db.query(ManagementModel).order_by(ManagementModel.management_code).offset(skip).limit(limit).all()


def update_management(db: Session, id_management: int, management: ManagementCreate) -> Optional[ManagementModel]:
    db_management = db.query(ManagementModel).filter(
        ManagementModel.id_management == id_management
    ).first()
    if db_management:
        for key, value in management.model_dump().items():
            setattr(db_management, key, value)
        db.commit()
        db.refresh(db_management)
    return db_management


def delete_management(db: Session, id_management: int) -> bool:
    db_management = db.query(ManagementModel).filter(
        ManagementModel.id_management == id_management
    ).first()
    if db_management:
        db.delete(db_management)
        db.commit()
        return True
    return False
