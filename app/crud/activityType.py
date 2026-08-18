# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.activityType import ActivityType as ActivityTypeModel
from app.schemas.activityType import ActivityTypeCreate, ActivityType as ActivityTypeSchema
import app.crud as crud
from app.crud.utils import statusRequest


def create_activity_type(db: Session, activity_type: ActivityTypeCreate) -> ActivityTypeSchema:
    db_activity_type = ActivityTypeModel(**activity_type.model_dump())
    db.add(db_activity_type)
    db.commit()
    db.refresh(db_activity_type)
    return db_activity_type


def get_activity_type_by_id(db: Session, id_activity_type: int) -> ActivityTypeSchema:
    return db.query(ActivityTypeModel).filter(ActivityTypeModel.id_activity_type == id_activity_type).first()


def get_activity_types(db: Session, skip: int = 0, limit: int = 10) -> list[ActivityTypeSchema]:
    return db.query(ActivityTypeModel).order_by(
        ActivityTypeModel.mandatory.desc(),
        ActivityTypeModel.activity_order.asc(),
        ActivityTypeModel.id_activity_type.asc()
    ).offset(skip).limit(limit).all()


def get_activity_types_mandatory(db: Session) -> list[ActivityTypeSchema]:
    return db.query(ActivityTypeModel).filter(
        ActivityTypeModel.mandatory == True
    ).order_by(
        ActivityTypeModel.activity_order.asc()
    ).all()


def update_activity_type(
    db: Session, id_activity_type: int,
    activity_type: ActivityTypeCreate
) -> ActivityTypeSchema:
    db_activity_type = db.query(ActivityTypeModel).filter(
        ActivityTypeModel.id_activity_type == id_activity_type).first()
    if db_activity_type:
        for key, value in activity_type.model_dump().items():
            setattr(db_activity_type, key, value)
        db.commit()
        db.refresh(db_activity_type)
    return db_activity_type


def delete_activity_type(db: Session, id_activity_type: int) -> dict[str, bool]:
    status = statusRequest()
    if len(crud.get_activities_by_id_activity_type(db, id_activity_type)) == 0:
        status['elimination_allow'] = True
        db_activity_type = db.query(ActivityTypeModel).filter(
            ActivityTypeModel.id_activity_type == id_activity_type).first()
        if db_activity_type:
            db.delete(db_activity_type)
            db.commit()
            status['deleted'] = True
    return status


def batch_reorder_mandatory_activities(
    db: Session,
    reorder_data: list[dict]
) -> list[ActivityTypeSchema]:
    """Reordenar múltiples actividades obligatorias de forma atómica."""
    try:
        updated_activities = []
        for item in reorder_data:
            db_activity = db.query(ActivityTypeModel).filter(
                ActivityTypeModel.id_activity_type == item['id_activity_type']
            ).first()

            if db_activity and db_activity.mandatory:
                db_activity.activity_order = item['activity_order']
                updated_activities.append(db_activity)

        db.commit()
        for activity in updated_activities:
            db.refresh(activity)
        return updated_activities
    except Exception as e:
        db.rollback()
        raise e


def renumber_mandatory_activities_after_delete(
    db: Session,
    deleted_order: int
) -> list[ActivityTypeSchema]:
    """Renumerar actividades obligatorias después de eliminar una."""
    try:
        activities_to_renumber = db.query(ActivityTypeModel).filter(
            ActivityTypeModel.mandatory == True,
            ActivityTypeModel.activity_order > deleted_order
        ).order_by(ActivityTypeModel.activity_order.asc()).all()

        for activity in activities_to_renumber:
            activity.activity_order -= 1

        db.commit()
        for activity in activities_to_renumber:
            db.refresh(activity)
        return activities_to_renumber
    except Exception as e:
        db.rollback()
        raise e
