from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.zone import Zone as ZoneModel
from app.schemas.zone import ZoneCreate


def create_zone(db: Session, zone: ZoneCreate) -> ZoneModel:
    db_zone = ZoneModel(**zone.model_dump())
    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)
    return db_zone


def get_zone_by_id(db: Session, id_zone: int) -> Optional[ZoneModel]:
    return db.query(ZoneModel).filter(
        ZoneModel.id_zone == id_zone
    ).first()


def get_zone_by_code(db: Session, zone_code: str) -> Optional[ZoneModel]:
    return db.query(ZoneModel).filter(
        ZoneModel.zone_code == zone_code
    ).first()


def get_zones(db: Session, skip: int = 0, limit: int = 50) -> List[ZoneModel]:
    return db.query(ZoneModel).order_by(ZoneModel.zone_code).offset(skip).limit(limit).all()


def update_zone(db: Session, id_zone: int, zone: ZoneCreate) -> Optional[ZoneModel]:
    db_zone = db.query(ZoneModel).filter(
        ZoneModel.id_zone == id_zone
    ).first()
    if db_zone:
        for key, value in zone.model_dump().items():
            setattr(db_zone, key, value)
        db.commit()
        db.refresh(db_zone)
    return db_zone


def delete_zone(db: Session, id_zone: int) -> bool:
    db_zone = db.query(ZoneModel).filter(
        ZoneModel.id_zone == id_zone
    ).first()
    if db_zone:
        db.delete(db_zone)
        db.commit()
        return True
    return False
