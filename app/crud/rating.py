# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

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
    return db.query(RatingModel).order_by(
        RatingModel.date_updated.desc()
    ).offset(skip).limit(limit).all()


def get_ratings_by_id_customer(db: Session, id_customer: int) -> list[RatingSchema]:
    return db.query(RatingModel).filter(RatingModel.id_customer == id_customer).order_by(
        RatingModel.date_updated.desc()
    ).all()


def get_rating_last_by_id_customer(db: Session, id_customer: int) -> RatingSchema:
    subquery = db.query(
        RatingModel.id_customer,
        func.max(RatingModel.date_updated).label("date_updated")
    ).group_by(
        RatingModel.id_customer
    ).subquery()

    return db.query(RatingModel).join(
        subquery,
        (RatingModel.id_customer == subquery.c.id_customer) &
        (RatingModel.date_updated == subquery.c.date_updated)
    ).filter(RatingModel.id_customer == id_customer).order_by(
        RatingModel.date_updated.desc(), RatingModel.id_rating.desc()
    ).first()


def get_ratings_last_full(db: Session, skip: int = 0, limit: int = 10) -> list[RatingSchema]:
    subquery = db.query(
        RatingModel.id_customer,
        func.max(RatingModel.date_updated).label("date_updated")
    ).group_by(
        RatingModel.id_customer
    ).subquery()

    return db.query(RatingModel).join(
        subquery,
        (RatingModel.id_customer == subquery.c.id_customer) &
        (RatingModel.date_updated == subquery.c.date_updated)
    ).offset(skip).limit(limit).all()


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
