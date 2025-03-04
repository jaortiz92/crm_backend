# Python
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func
import io
from pandas.core.frame import DataFrame

# App
from app.models.invoiceDetail import InvoiceDetail as InvoiceDetailModel
from app.models.brand import Brand as BrandModel
from app.schemas.invoiceDetail import InvoiceDetailCreate, InvoiceDetail as InvoiceDetailSchema
from app.utils.process_details import ProcessDetailsInvoice


def create_invoice_detail(db: Session, invoice_detail: InvoiceDetailCreate) -> InvoiceDetailSchema:
    db_invoice_detail = InvoiceDetailModel(**invoice_detail.model_dump())
    db.add(db_invoice_detail)
    db.commit()
    db.refresh(db_invoice_detail)
    return db_invoice_detail


async def create_invoice_details(db: Session, id_invoice: int, details: UploadFile) -> list[InvoiceDetailSchema]:
    stream = io.BytesIO()
    content = await details.read()
    stream.write(content)

    # Read Excel file from the BytesIO stream
    try:
        df: DataFrame = ProcessDetailsInvoice(
            stream, id_invoice
        ).final_details
    except Exception as e:
        print(e)
        return False

    # Delete last invoices_detail
    delete_invoices_detail_by_id_invoice(db, id_invoice)
    rows = df.to_dict(orient='records')
    db.bulk_insert_mappings(InvoiceDetailModel, rows)
    db.commit()
    return True


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


def delete_invoices_detail_by_id_invoice(db: Session, id_invoice: int):
    db.query(
        InvoiceDetailModel
    ).filter(
        InvoiceDetailModel.id_invoice == id_invoice
    ).delete(
        synchronize_session=False
    )

    db.commit()


def get_invoice_detail_by_brand_and_id_invoice(db: Session, id_invoice: int):
    result = db.query(
        BrandModel.brand_name,
        InvoiceDetailModel.gender,
        func.sum(InvoiceDetailModel.quantity).label("quantity"),
        func.sum(InvoiceDetailModel.value_without_tax).label(
            "discount"),
        func.sum(InvoiceDetailModel.value_without_tax).label(
            "value_without_tax"),
        func.sum(InvoiceDetailModel.value_with_tax).label("value_with_tax")
    ).join(
        BrandModel, InvoiceDetailModel.id_brand == BrandModel.id_brand
    ).filter(
        InvoiceDetailModel.id_invoice == id_invoice
    ).group_by(
        BrandModel.brand_name, InvoiceDetailModel.gender
    ).order_by(
        BrandModel.brand_name.asc(),
        InvoiceDetailModel.gender.desc()
    ).all()

    return result
