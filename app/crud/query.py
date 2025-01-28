# Python
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

# App
from app.models.query import (
    CustomerSummary as CustomerSummaryModel,
    CustomerTripSummary as CustomerTripSummaryModel
)


def get_customer_summary(db: Session, id_customer: int) -> list[CustomerSummaryModel]:
    result = db.query(CustomerSummaryModel).filter(
        CustomerSummaryModel.id_customer == id_customer
    ).all()
    return result


def get_customer_trip_summary(db: Session, id_customer_trip: int) -> list[CustomerTripSummaryModel]:
    result = db.query(CustomerTripSummaryModel).filter(
        CustomerTripSummaryModel.id_customer_trip == id_customer_trip
    ).all()
    return result
