# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.schemas.customerTrip import CustomerTripCreate
import app.crud as crud
from app.crud.utils import Constants


def get_customer_trip_by_id(db: Session, id_customer_trip: int) -> CustomerTripModel:
    return db.query(CustomerTripModel).filter(CustomerTripModel.id_customer_trip == id_customer_trip).first()


def get_customer_trips(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[CustomerTripModel]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(CustomerTripModel).order_by(
            CustomerTripModel.id_customer_trip.desc()).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        result = db.query(CustomerTripModel).filter(
            CustomerTripModel.id_seller == id_user).order_by(
            CustomerTripModel.id_customer_trip.desc()).offset(skip).limit(limit).all()
    return result


def get_customer_trips_by_id_customer(db: Session, id_customer) -> list[CustomerTripModel]:
    return db.query(CustomerTripModel).filter(CustomerTripModel.id_customer == id_customer).order_by(
        CustomerTripModel.id_customer_trip.desc()
    ).all()


def create_customer_trip(db: Session, customer_trip: CustomerTripCreate) -> CustomerTripModel:
    db_customer_trip = CustomerTripModel(**customer_trip.model_dump())
    db.add(db_customer_trip)
    db.commit()
    db.refresh(db_customer_trip)
    return db_customer_trip


def update_customer_trip(db: Session, id_customer_trip: int, customer_trip: CustomerTripCreate) -> CustomerTripModel:
    db_customer_trip = db.query(CustomerTripModel).filter(
        CustomerTripModel.id_customer_trip == id_customer_trip).first()

    if db_customer_trip:
        for key, value in customer_trip.model_dump().items():
            setattr(db_customer_trip, key, value)
        db.commit()
        db.refresh(db_customer_trip)
    return db_customer_trip


def delete_customer_trip(db: Session, id_customer_trip: int) -> bool:

    db_customer_trip = db.query(CustomerTripModel).filter(
        CustomerTripModel.id_customer_trip == id_customer_trip).first()
    db_activities = crud.get_activities_by_id_customer_trip(
        db, id_customer_trip
    )
    for db_activity in db_activities:
        crud.delete_activity(db, db_activity.id_activity)
    if db_customer_trip:
        db.delete(db_customer_trip)
        db.commit()
        return True
    return False
