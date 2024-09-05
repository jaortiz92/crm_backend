# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.credit import Credit as CreditModel
from app.schemas.credit import CreditCreate, Credit as CreditSchema


def create_credit(db: Session, credit: CreditCreate) -> CreditSchema:
    db_credit = CreditModel(**credit.model_dump())
    db.add(db_credit)
    db.commit()
    db.refresh(db_credit)
    return db_credit


def get_credit_by_id(db: Session, id_credit: int) -> CreditSchema:
    result = db.query(CreditModel).filter(
        CreditModel.id_credit == id_credit).first()
    return result


def get_credits(db: Session, skip: int = 0, limit: int = 10) -> list[CreditSchema]:
    return db.query(CreditModel).offset(skip).limit(limit).all()


def update_credit(db: Session, id_credit: int, credit: CreditCreate) -> CreditSchema:
    db_credit = db.query(CreditModel).filter(
        CreditModel.id_credit == id_credit).first()
    if db_credit:
        for key, value in credit.model_dump().items():
            setattr(db_credit, key, value)
        db.commit()
        db.refresh(db_credit)
    return db_credit


def delete_credit(db: Session, id_credit: int):
    db_credit = db.query(CreditModel).filter(
        CreditModel.id_credit == id_credit).first()
    if db_credit:
        db.delete(db_credit)
        db.commit()
        return True
    return False
