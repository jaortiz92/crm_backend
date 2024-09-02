# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.storeType import StoreType as StoreTypeModel
from app.schemas.storeType import StoreTypeCreate, StoreType as StoreTypeSchema


def create_storeType(db: Session, storeType: StoreTypeCreate) -> StoreTypeSchema:
    db_storeType = StoreTypeModel(**storeType.model_dump())
    db.add(db_storeType)
    db.commit()
    db.refresh(db_storeType)
    return db_storeType


def get_storeType_by_id(db: Session, id_store_type: int) -> StoreTypeSchema:
    result = db.query(StoreTypeModel).filter(
        StoreTypeModel.id_store_type == id_store_type).first()
    return result


def get_storeTypes(db: Session, skip: int = 0, limit: int = 10) -> list[StoreTypeSchema]:
    return db.query(StoreTypeModel).offset(skip).limit(limit).all()


def update_storeType(db: Session, id_store_type: int, storeType: StoreTypeCreate) -> StoreTypeSchema:
    db_storeType = db.query(StoreTypeModel).filter(
        StoreTypeModel.id_store_type == id_store_type).first()
    if db_storeType:
        for key, value in storeType.model_dump().items():
            setattr(db_storeType, key, value)
        db.commit()
        db.refresh(db_storeType)
    return db_storeType


def delete_storeType(db: Session, id_store_type: int):
    db_storeType = db.query(StoreTypeModel).filter(
        StoreTypeModel.id_store_type == id_store_type).first()
    if db_storeType:
        db.delete(db_storeType)
        db.commit()
        return True
    return False
