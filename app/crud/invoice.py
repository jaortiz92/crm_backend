# Python
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

# App
from app.models.invoice import Invoice as InvoiceModel
from app.models.order import Order as OrderModel
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.schemas.invoice import InvoiceCreate
from app.crud.utils import statusRequest
import app.crud as crud
from app.crud.utils import Constants


def create_invoice(db: Session, invoice: InvoiceCreate) -> InvoiceModel:
    status = statusRequest()
    db_invoice = InvoiceModel(**invoice.model_dump())
    if get_invoice_by_number_and_key(
        db, db_invoice.invoice_number, db_invoice.key
    ):
        status['value_already_registered'] = True
        return status
    elif crud.get_order_by_id(db, db_invoice.id_order):
        db.add(db_invoice)
        db.commit()
        db.refresh(db_invoice)
        return db_invoice
    else:
        return status


def get_invoice_by_id(db: Session, id_invoice: int) -> InvoiceModel:
    return db.query(InvoiceModel).filter(
        InvoiceModel.id_invoice == id_invoice).first()


def get_invoice_by_id_with_details(db: Session, id_invoice: int) -> InvoiceModel:
    return db.query(InvoiceModel).options(
        joinedload(InvoiceModel.invoice_details)
    ).filter(
        InvoiceModel.id_invoice == id_invoice
    ).first()


def get_invoice_by_number_and_key(db: Session, invoice_number: int, key: int) -> InvoiceModel:
    return db.query(InvoiceModel).filter(
        InvoiceModel.invoice_number == invoice_number,
        InvoiceModel.key == key
    ).first()


def get_invoices(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[InvoiceModel]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(InvoiceModel).order_by(
            InvoiceModel.id_invoice.desc()
        ).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        result = db.query(InvoiceModel).join(
            OrderModel, InvoiceModel.id_order == OrderModel.id_order
        ).filter(
            OrderModel.id_seller == id_user
        ).order_by(
            InvoiceModel.id_invoice.desc()
        ).offset(skip).limit(limit).all()
    return result


def get_invoices_by_customer_trip(db: Session, id_customer_trip: int) -> list[InvoiceModel]:
    return db.query(InvoiceModel).join(
        OrderModel, InvoiceModel.id_order == OrderModel.id_order
    ).filter(
        OrderModel.id_customer_trip == id_customer_trip
    )


def get_invoices_by_customer(db: Session, id_customer: int) -> list[InvoiceModel]:
    return db.query(InvoiceModel).join(
        OrderModel, InvoiceModel.id_order == OrderModel.id_order
    ).join(
        CustomerTripModel, OrderModel.id_customer_trip == CustomerTripModel.id_customer_trip
    ).filter(
        CustomerTripModel.id_customer == id_customer
    ).order_by(
        InvoiceModel.invoice_number.desc()
    )


def get_invoices_by_order(db: Session, id_order: int) -> list[InvoiceModel]:
    return db.query(InvoiceModel).filter(
        InvoiceModel.id_order == id_order
    )


def get_invoices_query(
    db: Session,
    invoice_number: str = None,
    key: int = None,
    date_ge: date = None,
    date_le: date = None,
    id_order: int = None,
) -> list[InvoiceModel]:
    query = db.query(InvoiceModel)
    if invoice_number is not None:
        query = query.filter(InvoiceModel.invoice_number == invoice_number)
    if key is not None:
        query = query.filter(InvoiceModel.key == key)
    if date_ge is not None:
        query = query.filter(InvoiceModel.invoice_date >= date_ge)
    if date_le is not None:
        query = query.filter(InvoiceModel.invoice_date <= date_le)
    if id_order is not None:
        query = query.filter(InvoiceModel.id_order == id_order)
    return query.order_by(
        InvoiceModel.invoice_date.desc()
    ).all()


def update_invoice(db: Session, id_invoice: int, invoice: InvoiceCreate) -> InvoiceModel:
    db_invoice = db.query(InvoiceModel).filter(
        InvoiceModel.id_invoice == id_invoice).first()
    if db_invoice:
        for key, value in invoice.model_dump().items():
            setattr(db_invoice, key, value)
        db.commit()
        db.refresh(db_invoice)
    return db_invoice


def delete_invoice(db: Session, id_invoice: int):
    db_invoice = db.query(InvoiceModel).filter(
        InvoiceModel.id_invoice == id_invoice).first()
    if db_invoice:
        db.delete(db_invoice)
        db.commit()
        return True
    return False
