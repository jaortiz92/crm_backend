# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.ratingCategory import RatingCategory as RatingCategoryModel
from app.schemas.ratingCategory import RatingCategoryCreate, RatingCategory as RatingCategorySchema


def create_ratingCategory(db: Session, ratingCategory: RatingCategoryCreate) -> RatingCategorySchema:
    db_ratingCategory = RatingCategoryModel(**ratingCategory.model_dump())
    db.add(db_ratingCategory)
    db.commit()
    db.refresh(db_ratingCategory)
    return db_ratingCategory


def get_ratingCategory_by_id(db: Session, id_rating_category: int) -> RatingCategorySchema:
    result = db.query(RatingCategoryModel).filter(
        RatingCategoryModel.id_rating_category == id_rating_category).first()
    return result


def get_ratingCategorys(db: Session, skip: int = 0, limit: int = 10) -> list[RatingCategorySchema]:
    return db.query(RatingCategoryModel).offset(skip).limit(limit).all()


def update_ratingCategory(db: Session, id_rating_category: int, ratingCategory: RatingCategoryCreate) -> RatingCategorySchema:
    db_ratingCategory = db.query(RatingCategoryModel).filter(
        RatingCategoryModel.id_rating_category == id_rating_category).first()
    if db_ratingCategory:
        for key, value in ratingCategory.model_dump().items():
            setattr(db_ratingCategory, key, value)
        db.commit()
        db.refresh(db_ratingCategory)
    return db_ratingCategory


def delete_ratingCategory(db: Session, id_rating_category: int):
    db_ratingCategory = db.query(RatingCategoryModel).filter(
        RatingCategoryModel.id_rating_category == id_rating_category).first()
    if db_ratingCategory:
        db.delete(db_ratingCategory)
        db.commit()
        return True
    return False
