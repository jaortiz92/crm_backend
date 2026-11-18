from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.area import Area as AreaModel
from app.schemas.area import AreaCreate


def create_area(db: Session, area: AreaCreate) -> AreaModel:
    db_area = AreaModel(**area.model_dump())
    db.add(db_area)
    db.commit()
    db.refresh(db_area)
    return db_area


def get_area_by_id(db: Session, id_area: int) -> Optional[AreaModel]:
    return db.query(AreaModel).filter(
        AreaModel.id_area == id_area
    ).first()


def get_area_by_code(db: Session, area_code: str) -> Optional[AreaModel]:
    return db.query(AreaModel).filter(
        AreaModel.area_code == area_code
    ).first()


def get_areas(
    db: Session,
    id_management: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[AreaModel]:
    query = db.query(AreaModel)
    if id_management is not None:
        query = query.filter(AreaModel.id_management == id_management)
    return query.order_by(AreaModel.area_code).offset(skip).limit(limit).all()


def update_area(db: Session, id_area: int, area: AreaCreate) -> Optional[AreaModel]:
    db_area = db.query(AreaModel).filter(
        AreaModel.id_area == id_area
    ).first()
    if db_area:
        for key, value in area.model_dump().items():
            setattr(db_area, key, value)
        db.commit()
        db.refresh(db_area)
    return db_area


def delete_area(db: Session, id_area: int) -> bool:
    db_area = db.query(AreaModel).filter(
        AreaModel.id_area == id_area
    ).first()
    if db_area:
        db.delete(db_area)
        db.commit()
        return True
    return False
