# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.originType import OriginType as OriginTypeModel
from app.schemas.originType import OriginTypeCreate, OriginType as OriginTypeSchema


def create_originType(db: Session, originType: OriginTypeCreate) -> OriginTypeSchema:
    db_originType = OriginTypeModel(**originType.model_dump())
    db.add(db_originType)
    db.commit()
    db.refresh(db_originType)
    return db_originType


def get_originType_by_id(db: Session, id_origin_type: int) -> OriginTypeSchema:
    result = db.query(OriginTypeModel).filter(
        OriginTypeModel.id_origin_type == id_origin_type).first()
    return result


def get_originTypes(db: Session, skip: int = 0, limit: int = 10) -> list[OriginTypeSchema]:
    return db.query(OriginTypeModel).offset(skip).limit(limit).all()


def update_originType(db: Session, id_origin_type: int, originType: OriginTypeCreate) -> OriginTypeSchema:
    db_originType = db.query(OriginTypeModel).filter(
        OriginTypeModel.id_origin_type == id_origin_type).first()
    if db_originType:
        for key, value in originType.model_dump().items():
            setattr(db_originType, key, value)
        db.commit()
        db.refresh(db_originType)
    return db_originType


def delete_originType(db: Session, id_origin_type: int):
    db_originType = db.query(OriginTypeModel).filter(
        OriginTypeModel.id_origin_type == id_origin_type).first()
    if db_originType:
        db.delete(db_originType)
        db.commit()
        return True
    return False
