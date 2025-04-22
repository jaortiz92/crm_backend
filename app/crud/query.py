# Python
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

# App
from app.models.query import (
    CustomerSummary as CustomerSummaryModel,
    CustomerTripSummary as CustomerTripSummaryModel,
    CollectionSummary as CollectionSummaryModel
)
import app.crud as crud
from app.crud.utils import Constants


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


def get_collection_summary(db: Session,  id_user: int, access_type: str) -> list[CollectionSummaryModel]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.FILTER:
        query = db.query(
            CustomerSummaryModel.collection_name,
            CustomerSummaryModel.short_collection_name,
            CustomerSummaryModel.year,
            CustomerSummaryModel.quarter,
            func.count(CustomerSummaryModel.id_customer
                       ).label("customers"),
            func.sum(CustomerSummaryModel.customer_trips
                     ).label("customer_trips"),
            func.sum(CustomerSummaryModel.budget
                     ).label("budget"),
            func.sum(CustomerSummaryModel.budget_quantities
                     ).label("budget_quantities"),
            func.sum(CustomerSummaryModel.orders
                     ).label("orders"),
            func.sum(CustomerSummaryModel.order_quantities
                     ).label("order_quantities"),
            func.sum(CustomerSummaryModel.order_without_tax
                     ).label("order_without_tax"),
            func.sum(CustomerSummaryModel.invoices
                     ).label("invoices"),
            func.sum(CustomerSummaryModel.invoice_quantities
                     ).label("invoice_quantities"),
            func.sum(CustomerSummaryModel.invoice_without_tax
                     ).label("invoice_without_tax"),
            func.sum(CustomerSummaryModel.invoice_discount
                     ).label("invoice_discount")
        )

        id_customers = crud.get_id_customers_by_seller(db, id_user)
        query = query.filter(
            CustomerSummaryModel.id_customer.in_(id_customers)
        )

        query = query.group_by(
            CustomerSummaryModel.collection_name,
            CustomerSummaryModel.short_collection_name,
            CustomerSummaryModel.year,
            CustomerSummaryModel.quarter
        ).order_by(
            CustomerSummaryModel.year.desc(),
            CustomerSummaryModel.quarter.desc(),
            CustomerSummaryModel.short_collection_name.asc()
        )

        result = query.all()
    elif auth == Constants.ALL:
        result = db.query(CollectionSummaryModel).all()

    return result
