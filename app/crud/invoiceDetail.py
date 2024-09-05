# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.invoiceDetail import InvoiceDetail as InvoiceDetailModel
from app.schemas.invoiceDetail import InvoiceDetailCreate, InvoiceDetail as InvoiceDetailSchema


def create_invoice_detail(db: Session, invoice_detail: InvoiceDetailCreate) -> InvoiceDetailSchema:
    db_invoice_detail = InvoiceDetailModel(**invoice_detail.model_dump())
    db.add(db_invoice_detail)
    db.commit()
    db.refresh(db_invoice_detail)
    return db_invoice_detail


def get_invoice_detail_by_id(db: Session, id_invoice_detail: int) -> InvoiceDetailSchema:
    result = db.query(InvoiceDetailModel).filter(
        InvoiceDetailModel.id_invoice_detail == id_invoice_detail).first()
    return result


def get_invoice_details(db: Session, skip: int = 0, limit: int = 10) -> list[InvoiceDetailSchema]:
    return db.query(InvoiceDetailModel).offset(skip).limit(limit).all()


def update_invoice_detail(db: Session, id_invoice_detail: int, invoice_detail: InvoiceDetailCreate) -> InvoiceDetailSchema:
    db_invoice_detail = db.query(InvoiceDetailModel).filter(
        InvoiceDetailModel.id_invoice_detail == id_invoice_detail).first()
    if db_invoice_detail:
        for key, value in invoice_detail.model_dump().items():
            setattr(db_invoice_detail, key, value)
        db.commit()
        db.refresh(db_invoice_detail)
    return db_invoice_detail


def delete_invoice_detail(db: Session, id_invoice_detail: int):
    db_invoice_detail = db.query(InvoiceDetailModel).filter(
        InvoiceDetailModel.id_invoice_detail == id_invoice_detail).first()
    if db_invoice_detail:
        db.delete(db_invoice_detail)
        db.commit()
        return True
    return False
