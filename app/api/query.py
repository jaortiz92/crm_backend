# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import CustomerSummary, CustomerTripSummary
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

query = APIRouter(
    prefix="/query",
    tags=["Query"],
)


@query.get("/customer_summary/{id_customer}", response_model=List[CustomerSummary])
def get_customer_summary(id_customer: int, db: Session = Depends(get_db)):
    """
    Show a summary about custommer
    """
    db_rating = crud.get_customer_summary(db, id_customer)
    if db_rating is None:
        Exceptions.register_not_found("Custommer Summary", id_customer)
    return db_rating


@query.get("/customer_trip_summary/{id_customer_trip}", response_model=List[CustomerTripSummary])
def get_customer_summary(id_customer_trip: int, db: Session = Depends(get_db)):
    """
    Show a summary about custommer trip
    """
    db_rating = crud.get_customer_trip_summary(db, id_customer_trip)
    if db_rating is None:
        Exceptions.register_not_found(
            "Custommer Trip Summary", id_customer_trip)
    return db_rating
