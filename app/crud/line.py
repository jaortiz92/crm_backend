# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.line import Line as LineModel
from app.schemas.line import LineCreate, Line as LineSchema


def create_line(db: Session, line: LineCreate) -> LineSchema:
    db_line = LineModel(**line.model_dump())
    db.add(db_line)
    db.commit()
    db.refresh(db_line)
    return db_line


def get_line_by_id(db: Session, id_line: int) -> LineSchema:
    result = db.query(LineModel).filter(
        LineModel.id_line == id_line).first()
    return result


def get_lines(db: Session, skip: int = 0, limit: int = 10) -> list[LineSchema]:
    return db.query(LineModel).offset(skip).limit(limit).all()


def update_line(db: Session, id_line: int, line: LineCreate) -> LineSchema:
    db_line = db.query(LineModel).filter(
        LineModel.id_line == id_line).first()
    if db_line:
        for key, value in line.model_dump().items():
            setattr(db_line, key, value)
        db.commit()
        db.refresh(db_line)
    return db_line


def delete_line(db: Session, id_line: int):
    db_line = db.query(LineModel).filter(
        LineModel.id_line == id_line).first()
    if db_line:
        db.delete(db_line)
        db.commit()
        return True
    return False
