# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.rating import Rating as RatingModel
from app.schemas.rating import RatingCreate, Rating as RatingSchema


def create_rating(db: Session, rating: RatingCreate) -> RatingSchema:
    db_rating = RatingModel(**rating.model_dump())
    db.add(db_rating)
    db.commit()
    db.refresh(db_rating)
    return db_rating


def get_rating_by_id(db: Session, id_rating: int) -> RatingSchema:
    result = db.query(RatingModel).filter(
        RatingModel.id_rating == id_rating).first()
    return result


def get_ratings(db: Session, skip: int = 0, limit: int = 10) -> list[RatingSchema]:
    return db.query(RatingModel).offset(skip).limit(limit).all()


def update_rating(db: Session, id_rating: int, rating: RatingCreate) -> RatingSchema:
    db_rating = db.query(RatingModel).filter(
        RatingModel.id_rating == id_rating).first()
    if db_rating:
        for key, value in rating.model_dump().items():
            setattr(db_rating, key, value)
        db.commit()
        db.refresh(db_rating)
    return db_rating


def delete_rating(db: Session, id_rating: int) -> bool:
    db_rating = db.query(RatingModel).filter(
        RatingModel.id_rating == id_rating).first()
    if db_rating:
        db.delete(db_rating)
        db.commit()
        return True
    return False
