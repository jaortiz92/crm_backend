# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.invoice import Invoice as InvoiceModel
from app.schemas.invoice import InvoiceCreate, Invoice as InvoiceSchema


def create_invoice(db: Session, invoice: InvoiceCreate) -> InvoiceSchema:
    db_invoice = InvoiceModel(**invoice.model_dump())
    db.add(db_invoice)
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


def get_invoice_by_id(db: Session, id_invoice: int) -> InvoiceSchema:
    result = db.query(InvoiceModel).filter(
        InvoiceModel.id_invoice == id_invoice).first()
    return result


def get_invoices(db: Session, skip: int = 0, limit: int = 10) -> list[InvoiceSchema]:
    return db.query(InvoiceModel).offset(skip).limit(limit).all()


def update_invoice(db: Session, id_invoice: int, invoice: InvoiceCreate) -> InvoiceSchema:
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
