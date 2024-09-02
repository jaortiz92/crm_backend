# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.collection import Collection as CollectionModel
from app.schemas.collection import CollectionCreate, Collection as CollectionSchema


def create_collection(db: Session, collection: CollectionCreate) -> CollectionSchema:
    db_collection = CollectionModel(**collection.model_dump())
    db.add(db_collection)
    db.commit()
    db.refresh(db_collection)
    return db_collection


def get_collection_by_id(db: Session, id_collection: int) -> CollectionSchema:
    result = db.query(CollectionModel).filter(
        CollectionModel.id_collection == id_collection).first()
    return result


def get_collections(db: Session, skip: int = 0, limit: int = 10) -> list[CollectionSchema]:
    return db.query(CollectionModel).offset(skip).limit(limit).all()


def update_collection(db: Session, id_collection: int, collection: CollectionCreate) -> CollectionSchema:
    db_collection = db.query(CollectionModel).filter(
        CollectionModel.id_collection == id_collection).first()
    if db_collection:
        for key, value in collection.model_dump().items():
            setattr(db_collection, key, value)
        db.commit()
        db.refresh(db_collection)
    return db_collection


def delete_collection(db: Session, id_collection: int):
    db_collection = db.query(CollectionModel).filter(
        CollectionModel.id_collection == id_collection).first()
    if db_collection:
        db.delete(db_collection)
        db.commit()
        return True
    return False
