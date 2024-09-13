# Python
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

# App
from app.models.invoice import Invoice as InvoiceModel
from app.schemas.invoice import InvoiceCreate
from app.models.invoiceDetail import InvoiceDetail as InvoiceDetailModel
from app.crud import utils
import app.crud as crud


def create_invoice(db: Session, invoice: InvoiceCreate) -> InvoiceModel:
    status = utils.statusRequest()
    db_invoice = InvoiceModel(**invoice.model_dump())
    if crud.get_order_by_id(db, db_invoice.id_order):
        db.add(db_invoice)
        db.commit()
        db.refresh(db_invoice)
        return db_invoice
    else:
        status


def get_invoice_by_id(db: Session, id_invoice: int) -> InvoiceModel:
    subquery = db.query(
        InvoiceDetailModel.id_invoice,
        func.sum(InvoiceDetailModel.quantity).label("quantity"),
        func.sum(InvoiceDetailModel.value_without_tax).label(
            "value_without_tax"),
        func.sum(InvoiceDetailModel.value_with_tax).label("value_with_tax")
    ).group_by(
        InvoiceDetailModel.id_invoice
    ).filter(InvoiceDetailModel.id_invoice == id_invoice).subquery()

    return db.query(InvoiceModel).join(
        subquery,
        InvoiceModel.id_invoice == subquery.c.id_invoice
    ).filter(
        InvoiceModel.id_invoice == id_invoice
    ).first()


def get_invoices(db: Session, skip: int = 0, limit: int = 10) -> list[InvoiceModel]:
    return db.query(
        InvoiceModel,
        func.sum(InvoiceDetailModel.quantity).label("quantity"),
        func.sum(InvoiceDetailModel.value_without_tax).label(
            "value_without_tax"),
        func.sum(InvoiceDetailModel.value_with_tax).label("value_with_tax")
    ).join(InvoiceDetailModel).group_by(InvoiceModel).order_by(InvoiceModel.invoice_date.desc()).offset(skip).limit(limit).all()


def get_invoices_query(
    db: Session,
    id_customer: int = None,
    id_creator: int = None,
    id_responsible: int = None,
    creation_date_ge: date = None,
    creation_date_le: date = None,
    completed: bool = None,
    closing_date_ge: date = None,
    closing_date_le: date = None,
) -> list[InvoiceModel]:
    query = db.query(InvoiceModel)
    if id_customer is not None:
        query = query.filter(InvoiceModel.id_customer == id_customer)
    if id_creator is not None:
        query = query.filter(InvoiceModel.id_creator == id_creator)
    if id_responsible is not None:
        query = query.filter(InvoiceModel.id_responsible == id_responsible)
    if creation_date_ge is not None:
        query = query.filter(InvoiceModel.creation_date >= creation_date_ge)
    if creation_date_le is not None:
        query = query.filter(InvoiceModel.creation_date <= creation_date_le)
    if completed is not None:
        query = query.filter(InvoiceModel.completed == completed)
    if closing_date_ge is not None:
        query = query.filter(InvoiceModel.closing_date >= closing_date_ge)
    if closing_date_le is not None:
        query = query.filter(InvoiceModel.closing_date <= closing_date_le)
    return query.order_by(
        InvoiceModel.creation_date.desc()
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
