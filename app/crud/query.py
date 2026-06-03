# Python
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_, or_
from fastapi import UploadFile
import io
import pandas as pd


# App
from app.models.query import (
    CustomerSummary as CustomerSummaryModel,
    CustomerTripSummary as CustomerTripSummaryModel,
    CollectionSummary as CollectionSummaryModel
)
from app.models import Customer as CustomerModel
from app.models.order import Order as OrderModel
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.models.user import User as UserModel
from app.models.collection import Collection as CollectionModel
from app.models.invoice import Invoice as InvoiceModel
from app.models.line import Line as LineModel
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


def validate_customer_documents(db: Session, documents: list[float]) -> list[CustomerModel]:
    return db.query(CustomerModel).filter(
        CustomerModel.document.in_(documents)
    ).all()


async def validate_customers_from_file(db: Session, file: UploadFile) -> list[dict]:
    content = await file.read()
    df = pd.read_excel(io.BytesIO(content))

    if df.empty:
        return []

    # Flexible column search for "Documento", "document", "nit", "id", or default to the first column
    doc_col = None
    for col in df.columns:
        if str(col).strip().lower() in ["documento", "document", "doc", "nit", "id", "identificacion"]:
            doc_col = col
            break

    if doc_col is None:
        doc_col = df.columns[0]

    # Get unique document values and clean them
    raw_documents = df[doc_col].dropna().unique()

    cleaned_docs = []
    doc_map = {}  # Keep mapping of cleaned float to original representation

    for doc in raw_documents:
        try:
            float_val = float(doc)
            cleaned_docs.append(float_val)
            doc_map[float_val] = doc
        except (ValueError, TypeError):
            # Skip rows that cannot be converted to floats
            pass

    if not cleaned_docs:
        return []

    # Query database in bulk
    existing_customers = validate_customer_documents(db, cleaned_docs)

    # Map by document
    customer_map = {cust.document: cust for cust in existing_customers}

    results = []
    for float_doc in cleaned_docs:
        cust = customer_map.get(float_doc)
        if cust:
            seller_name = f"{cust.seller.first_name} {cust.seller.last_name}" if cust.seller else None
            results.append({
                "document": float_doc,
                "exists": True,
                "company_name": cust.company_name,
                "email": cust.email,
                "phone": cust.phone,
                "active": cust.active,
                "seller": seller_name
            })
        else:
            results.append({
                "document": float_doc,
                "exists": False,
                "company_name": None,
                "email": None,
                "phone": None,
                "active": None,
                "seller": None
            })

    return results


def get_orders_without_invoices(closed: bool, db: Session, id_user: int, access_type: str) -> list:
    auth = Constants.get_auth_to_customers(access_type)

    query = db.query(
        OrderModel.id_order,
        OrderModel.date_order,
        OrderModel.delivery_date,
        OrderModel.total_quantities,
        OrderModel.total_with_tax,
        CustomerModel.company_name,
        (UserModel.first_name + " " + UserModel.last_name).label("seller_name"),
        CollectionModel.collection_name,
        LineModel.line_name,
        OrderModel.id_customer_trip
    ).select_from(OrderModel)\
     .join(CustomerTripModel, OrderModel.id_customer_trip == CustomerTripModel.id_customer_trip)\
     .join(CustomerModel, CustomerTripModel.id_customer == CustomerModel.id_customer)\
     .join(UserModel, OrderModel.id_seller == UserModel.id_user)\
     .join(CollectionModel, CustomerTripModel.id_collection == CollectionModel.id_collection)\
     .join(LineModel, CollectionModel.id_line == LineModel.id_line)\
     .outerjoin(InvoiceModel, OrderModel.id_order == InvoiceModel.id_order)\
     .filter(
         InvoiceModel.id_invoice == None,
         CustomerTripModel.closed == closed
    )

    if auth == Constants.FILTER:
        id_customers = crud.get_id_customers_by_seller(db, id_user)
        query = query.filter(
            or_(
                CustomerTripModel.id_customer.in_(id_customers),
                CustomerTripModel.id_seller == id_user,
                OrderModel.id_seller == id_user
            )
        )

    query = query.order_by(OrderModel.date_order.desc())
    results = query.all()

    return [
        {
            "id_order": r.id_order,
            "date_order": r.date_order,
            "delivery_date": r.delivery_date,
            "total_quantities": r.total_quantities,
            "total_with_tax": r.total_with_tax,
            "company_name": r.company_name,
            "seller_name": r.seller_name,
            "collection_name": r.collection_name,
            "line_name": r.line_name,
            "id_customer_trip": r.id_customer_trip
        }
        for r in results
    ]
