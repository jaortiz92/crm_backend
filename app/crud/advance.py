# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.advance import Advance as AdvanceModel
from app.schemas.advance import AdvanceCreate, Advance as AdvanceSchema


def create_advance(db: Session, advance: AdvanceCreate) -> AdvanceSchema:
    db_advance = AdvanceModel(**advance.model_dump())
    db.add(db_advance)
    db.commit()
    db.refresh(db_advance)
    return db_advance


def get_advance_by_id(db: Session, id_advance: int) -> AdvanceSchema:
    result = db.query(AdvanceModel).filter(
        AdvanceModel.id_advance == id_advance).first()
    return result


def get_advances(db: Session, skip: int = 0, limit: int = 10) -> list[AdvanceSchema]:
    return db.query(AdvanceModel).offset(skip).limit(limit).all()


def update_advance(db: Session, id_advance: int, advance: AdvanceCreate) -> AdvanceSchema:
    db_advance = db.query(AdvanceModel).filter(
        AdvanceModel.id_advance == id_advance).first()
    if db_advance:
        for key, value in advance.model_dump().items():
            setattr(db_advance, key, value)
        db.commit()
        db.refresh(db_advance)
    return db_advance


def delete_advance(db: Session, id_advance: int):
    db_advance = db.query(AdvanceModel).filter(
        AdvanceModel.id_advance == id_advance).first()
    if db_advance:
        db.delete(db_advance)
        db.commit()
        return True
    return False
