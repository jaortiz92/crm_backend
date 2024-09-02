# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.brand import Brand as BrandModel
from app.schemas.brand import BrandCreate, Brand as BrandSchema


def create_brand(db: Session, brand: BrandCreate) -> BrandSchema:
    db_brand = BrandModel(**brand.model_dump())
    db.add(db_brand)
    db.commit()
    db.refresh(db_brand)
    return db_brand


def get_brand_by_id(db: Session, id_brand: int) -> BrandSchema:
    result = db.query(BrandModel).filter(
        BrandModel.id_brand == id_brand).first()
    return result


def get_brands(db: Session, skip: int = 0, limit: int = 10) -> list[BrandSchema]:
    return db.query(BrandModel).offset(skip).limit(limit).all()


def update_brand(db: Session, id_brand: int, brand: BrandCreate) -> BrandSchema:
    db_brand = db.query(BrandModel).filter(
        BrandModel.id_brand == id_brand).first()
    if db_brand:
        for key, value in brand.model_dump().items():
            setattr(db_brand, key, value)
        db.commit()
        db.refresh(db_brand)
    return db_brand


def delete_brand(db: Session, id_brand: int):
    db_brand = db.query(BrandModel).filter(
        BrandModel.id_brand == id_brand).first()
    if db_brand:
        db.delete(db_brand)
        db.commit()
        return True
    return False
