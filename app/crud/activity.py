# Python
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.activity import Activity as ActivityModel
from app.schemas.activity import ActivityCreate, Activity as ActivitySchema
from app.models.customerTrip import CustomerTrip as CustomerTripModel


def create_activity(db: Session, activity: ActivityCreate) -> ActivitySchema:
    db_activity = ActivityModel(**activity.model_dump())
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity


def get_activity_by_id(db: Session, id_activity: int) -> ActivitySchema:
    return db.query(ActivityModel).filter(ActivityModel.id_activity == id_activity).first()


def get_activities(db: Session, skip: int = 0, limit: int = 10) -> list[ActivitySchema]:
    return db.query(ActivityModel).order_by(
        ActivityModel.estimated_date.desc()
    ).offset(skip).limit(limit).all()


def get_activities_by_id_customer_trip(db: Session, id_customer_trip: int) -> list[ActivitySchema]:
    return db.query(ActivityModel).filter(
        ActivityModel.id_customer_trip == id_customer_trip
    ).order_by(
        ActivityModel.estimated_date.desc()
    ).all()


def get_activities_by_id_activity_type(db: Session, id_activity_type: int) -> list[ActivitySchema]:
    return db.query(ActivityModel).filter(
        ActivityModel.id_activity_type == id_activity_type
    ).order_by(
        ActivityModel.estimated_date.desc()
    ).all()

def get_activities_query(
        db: Session,
        id_customer_trip: int = None,
        id_customer: int = None,
        id_activity_type: int = None,
        id_user: int = None,
        estimated_date_ge: date = None,
        estimated_date_le: date = None,
        completed: bool = None,
        execution_date_ge: date = None,
        execution_date_le: date = None,  
    ) -> list[ActivitySchema]:
    query = db.query(ActivityModel)
    if id_customer_trip is not None:
        query = query.filter(ActivityModel.id_customer_trip == id_customer_trip)
    if id_activity_type is not None:
        query = query.filter(ActivityModel.id_activity_type == id_activity_type)
    if id_user is not None:
        query = query.filter(ActivityModel.id_user == id_user)
    if estimated_date_ge is not None:
        query = query.filter(ActivityModel.estimated_date >= estimated_date_ge)
    if estimated_date_le is not None:
        query = query.filter(ActivityModel.estimated_date <= estimated_date_le)
    if completed is not None:
        query = query.filter(ActivityModel.completed == completed)
    if execution_date_ge is not None:
        query = query.filter(ActivityModel.execution_date >= execution_date_ge)
    if execution_date_le is not None:
        query = query.filter(ActivityModel.execution_date <= execution_date_le)
    if id_customer is not None:
        query = query.join(CustomerTripModel).filter(CustomerTripModel.id_customer == id_customer)
    return query.order_by(
        ActivityModel.estimated_date.desc()
    ).all()


def update_activity(db: Session, id_activity: int, activity: ActivityCreate) -> ActivitySchema:
    db_activity = db.query(ActivityModel).filter(
        ActivityModel.id_activity == id_activity).first()
    if db_activity:
        for key, value in activity.model_dump().items():
            setattr(db_activity, key, value)
        db.commit()
        db.refresh(db_activity)
    return db_activity


def delete_activity(db: Session, id_activity: int) -> bool:
    db_activity = db.query(ActivityModel).filter(
        ActivityModel.id_activity == id_activity).first()
    if db_activity:
        db.delete(db_activity)
        db.commit()
        return True
    return False
