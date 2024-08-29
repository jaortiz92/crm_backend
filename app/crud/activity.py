# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.activity import Activity as ActivityModel
from app.schemas.activity import ActivityCreate, Activity as ActivitySchema


def create_activity(db: Session, activity: ActivityCreate) -> ActivitySchema:
    db_activity = ActivityModel(**activity.model_dump())
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity

def get_activity(db: Session, id_activity: int) -> ActivitySchema:
    return db.query(ActivityModel).filter(ActivityModel.id_activity == id_activity).first()

def get_activities(db: Session, skip: int = 0, limit: int = 10) -> list[ActivitySchema]:
    return db.query(ActivityModel).order_by(
        ActivityModel.estimated_date.desc()
    ).offset(skip).limit(limit).all()

def update_activity(db: Session, id_activity: int, activity: ActivityCreate) -> ActivitySchema:
    db_activity = db.query(ActivityModel).filter(ActivityModel.id_activity == id_activity).first()
    if db_activity:
        for key, value in activity.model_dump().items():
            setattr(db_activity, key, value)
        db.commit()
        db.refresh(db_activity)
    return db_activity

def delete_activity(db: Session, id_activity: int) -> bool:
    db_activity = db.query(ActivityModel).filter(ActivityModel.id_activity == id_activity).first()
    if db_activity:
        db.delete(db_activity)
        db.commit()
        return True
    return False