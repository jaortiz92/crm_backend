# Python
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

# App
from app.models.activity import Activity as ActivityModel
from app.schemas.activity import ActivityCreate, ActivityAuthorize,  Activity as ActivitySchema
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.crud.utils import Constants
import app.crud as crud


def validate_foreign_keys(db: Session, activity: ActivitySchema) -> list:
    foreign_keys: list[list] = [
        [crud.get_customer_trip_by_id, activity.id_customer_trip, "Custormer Trip"],
        [crud.get_user_by_id, activity.id_user, "User"],
        [crud.get_activity_type_by_id, activity.id_activity_type]
    ]
    for foreign_key in foreign_keys:
        if not foreign_key[0](db, foreign_key[1]):
            return [foreign_key[2], foreign_key[1]]
    return Constants.STATUS_OK


def create_activity(db: Session, activity: ActivityCreate) -> ActivitySchema:
    validation: list = validate_foreign_keys(db, activity)
    if validation != Constants.STATUS_OK:
        return validation
    else:
        db_activity = ActivityModel(
            creation_date=date.today(), **activity.model_dump()
        )
        db.add(db_activity)
        db.commit()
        db.refresh(db_activity)
        return db_activity


def get_activity_by_id(db: Session, id_activity: int) -> ActivitySchema:
    return db.query(ActivityModel).filter(ActivityModel.id_activity == id_activity).first()


def get_activities(db: Session,  id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[ActivitySchema]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(ActivityModel).order_by(
            ActivityModel.estimated_date.asc()
        ).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        result = db.query(ActivityModel).filter(
            ActivityModel.id_user == id_user
        ).order_by(
            ActivityModel.estimated_date.asc()
        ).offset(skip).limit(limit).all()
    return result


def get_activities_by_id_customer_trip(db: Session, id_customer_trip: int) -> list[ActivitySchema]:
    return db.query(ActivityModel).filter(
        ActivityModel.id_customer_trip == id_customer_trip
    ).order_by(
        ActivityModel.completed.asc(), ActivityModel.estimated_date.asc(),
        ActivityModel.id_activity.asc()
    ).all()


def get_activities_pending(db: Session,  id_user: int, access_type: str) -> list[ActivitySchema]:
    auth = Constants.get_auth_to_customers(access_type)
    if auth == Constants.ALL:
        result = db.query(ActivityModel).join(
            CustomerTripModel, ActivityModel.id_customer_trip == CustomerTripModel.id_customer_trip
        ).filter(
            and_(
                ActivityModel.completed != True,
                CustomerTripModel.closed != True
            )
        ).order_by(
            ActivityModel.estimated_date.asc()
        ).all()
    elif auth == Constants.FILTER:
        id_customers: list[int] = crud.get_id_customers_by_seller(db, id_user)

        result = db.query(ActivityModel).join(
            CustomerTripModel, ActivityModel.id_customer_trip == CustomerTripModel.id_customer_trip
        ).filter(
            and_(
                ActivityModel.completed == False,
                CustomerTripModel.closed == False,
                or_(
                    CustomerTripModel.id_customer.in_(id_customers),
                    CustomerTripModel.id_seller == id_user,
                    ActivityModel.id_user == id_user
                )
            )
        ).order_by(
            ActivityModel.estimated_date.asc()
        ).all()
    return result


def get_activities_by_id_activity_type(db: Session, id_activity_type: int) -> list[ActivitySchema]:
    return db.query(ActivityModel).filter(
        ActivityModel.id_activity_type == id_activity_type
    ).order_by(
        ActivityModel.estimated_date.asc()
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
        query = query.filter(
            ActivityModel.id_customer_trip == id_customer_trip)
    if id_activity_type is not None:
        query = query.filter(
            ActivityModel.id_activity_type == id_activity_type)
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
        query = query.join(CustomerTripModel).filter(
            CustomerTripModel.id_customer == id_customer)
    return query.order_by(
        ActivityModel.estimated_date.asc(), ActivityModel.completed.asc(),
        ActivityModel.id_activity.asc()
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


def authorize_activity(db: Session, id_activity: int, activity: ActivityAuthorize) -> ActivitySchema:
    db_activity = db.query(ActivityModel).filter(
        ActivityModel.id_activity == id_activity).first()
    if db_activity:
        for key, value in activity.model_dump().items():
            setattr(db_activity, key, value)
        setattr(db_activity, "date_authorized", date.today())
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
