# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.activityType import ActivityType as ActivityTypeModel
from app.schemas.activityType import ActivityTypeCreate, ActivityType as ActivityTypeSchema



def create_activity_type(db: Session, activity_type: ActivityTypeCreate) -> ActivityTypeSchema:
    db_activity_type = ActivityTypeModel(**activity_type.dict())
    db.add(db_activity_type)
    db.commit()
    db.refresh(db_activity_type)
    return db_activity_type

def get_activity_type_by_id(db: Session, id_activity_type: int) -> ActivityTypeSchema:
    return db.query(ActivityTypeModel).filter(ActivityTypeModel.id_activity_type == id_activity_type).first()

def get_activity_types(db: Session, skip: int = 0, limit: int = 10) -> list[ActivityTypeSchema]:
    return db.query(ActivityTypeModel).order_by(
        ActivityTypeModel.activity_order.desc()
    ).offset(skip).limit(limit).all()

def update_activity_type(
        db: Session, id_activity_type: int,
        activity_type: ActivityTypeCreate
    ) -> ActivityTypeSchema:
    db_activity_type = db.query(ActivityTypeModel).filter(ActivityTypeModel.id_activity_type == id_activity_type).first()
    if db_activity_type:
        for key, value in activity_type.dict().items():
            setattr(db_activity_type, key, value)
        db.commit()
        db.refresh(db_activity_type)
    return db_activity_type

def delete_activity_type(db: Session, id_activity_type: int):
    db_activity_type = db.query(ActivityTypeModel).filter(ActivityTypeModel.id_activity_type == id_activity_type).first()
    if db_activity_type:
        db.delete(db_activity_type)
        db.commit()
        return True
    return False