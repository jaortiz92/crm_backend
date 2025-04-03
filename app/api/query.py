# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import CustomerSummary, CustomerTripSummary, CollectionSummary, User
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions
from app.core.auth import get_current_user

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


@query.get("/collection_summary", response_model=List[CollectionSummary])
def get_collection_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_type: str = Depends(crud.get_me_access_type)
):
    """
    Show a summary about collection
    """
    db_rating = crud.get_collection_summary(
        db, current_user.id_user, access_type
    )
    return db_rating
