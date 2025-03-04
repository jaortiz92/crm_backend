# Python
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import InvoiceDetail, InvoiceDetailCreate, InvoiceDetailFull, InvoiceDetailByBrand
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

invoice_detail = APIRouter(
    prefix="/invoice_detail",
    tags=["InvoiceDetail"],
)


@invoice_detail.get("/{id_invoice_detail}", response_model=InvoiceDetail)
def get_invoice_detail_by_id(id_invoice_detail: int, db: Session = Depends(get_db)):
    """
    Show an Invoice Detail

    This path operation shows an invoice detail in the app.

    Parameters:
    - Register path parameter
        - id_invoice_detail: int

    Returns a JSON with the invoice detail:
        - id_invoice integer
        - product string
        - color string
        - size string
        - id_brand integer
        - gender integer
        - unit_value float
        - quantity integer
        - value_without_tax float
        - discount float
        - value_with_tax float
        - id_invoice_detail
    """
    db_invoice_detail = crud.get_invoice_detail_by_id(db, id_invoice_detail)
    if db_invoice_detail is None:
        Exceptions.register_not_found("Invoice Detail", id_invoice_detail)
    return db_invoice_detail


@invoice_detail.get("/full/{id_invoice_detail}", response_model=InvoiceDetailFull)
def get_invoice_detail_by_id_full(id_invoice_detail: int, db: Session = Depends(get_db)):
    """
    Show an Invoice Detail Full

    This path operation shows an invoice detail full in the app.

    Parameters:
    - Register path parameter
        - id_invoice_detail: int

    Returns a JSON with the invoice detail full:
        - id_invoice integer
        - product string
        - color string
        - size string
        - id_brand integer
        - gender integer
        - unit_value float
        - quantity integer
        - value_without_tax float
        - discount float
        - value_with_tax float
        - id_invoice_detail
        - invoice: InvoiceBase
        - brand: BrandFull
    """
    db_invoice_detail = crud.get_invoice_detail_by_id(db, id_invoice_detail)
    if db_invoice_detail is None:
        Exceptions.register_not_found("Invoice Detail", id_invoice_detail)
    return db_invoice_detail


@invoice_detail.get("/", response_model=List[InvoiceDetail])
def get_invoice_details(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show invoice details

    This path operation shows a list of invoice details in the app with a limit on the number of invoice details.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoice details to retrieve (default: 10)

    Returns a JSON with a list of invoice details in the app.
    """
    return crud.get_invoice_details(db, skip=skip, limit=limit)


@invoice_detail.get("/full/", response_model=List[InvoiceDetailFull])
def get_invoice_details_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show invoice details full

    This path operation shows a list of invoice details full in the app with a limit on the number of invoice details full.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoice details full to retrieve (default: 10)

    Returns a JSON with a list of invoice details full in the app.
    """
    return crud.get_invoice_details(db, skip=skip, limit=limit)


@invoice_detail.post("/", response_model=InvoiceDetail)
def create_invoice_detail(invoice_detail: InvoiceDetailCreate, db: Session = Depends(get_db)):
    """
    Create an InvoiceDetail

    This path operation creates a new invoice_detail in the app.

    Parameters:
    - Request body parameter
        - invoice_detail: InvoiceDetailCreate -> A JSON object containing the following keys:
            - invoice_detail_number: str
            - invoice_detail_date: date
            - id_order: int

    Returns a JSON with the newly created invoice_detail:
    - id_invoice_detail: int
    - invoice_detail_number: str
    - invoice_detail_date: date
    - id_order: int
    """
    return crud.create_invoice_detail(db, invoice_detail)


@invoice_detail.post("/file/{id_invoice}")
async def create_invoice_details(id_invoice: int, details: UploadFile = File(...), db: Session = Depends(get_db)):
    if not details.filename.endswith(('xlsx', 'xlsm')):
        Exceptions.conflict_with_register('File Format', details.filename)
    result = await crud.create_invoice_details(db, id_invoice, details)
    if result:
        return {"message": "Orders detail to invoice was {id_invoice} created"}
    else:
        return Exceptions.conflict_with_register('File', details.filename)


@invoice_detail.put("/{id_invoice_detail}", response_model=InvoiceDetail)
def update_invoice_detail(id_invoice_detail: int, invoice_detail: InvoiceDetailCreate, db: Session = Depends(get_db)):
    """
    Update an InvoiceDetail

    This path operation updates an existing invoice_detail in the app.

    Parameters:
    - Register path parameter
        - id_invoice_detail: int
    - Request body parameter
        - invoice_detail: InvoiceDetailCreate -> A JSON object containing the updated invoice_detail data:
            - invoice_detail_number: str
            - invoice_detail_date: date
            - id_order: int

    Returns a JSON with the updated invoice_detail:
    - id_invoice_detail: int
    - invoice_detail_number: str
    - invoice_detail_date: date
    - id_order: int
    """
    db_invoice_detail = crud.update_invoice_detail(
        db, id_invoice_detail, invoice_detail)
    if db_invoice_detail is None:
        Exceptions.register_not_found("Invoice Detail", id_invoice_detail)
    return db_invoice_detail


@invoice_detail.delete("/{id_invoice_detail}")
def delete_invoice_detail(id_invoice_detail: int, db: Session = Depends(get_db)):
    """
    Delete an InvoiceDetail

    This path operation deletes an invoice_detail from the app.

    Parameters:
    - Register path parameter
        - id_invoice_detail: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_invoice_detail(db, id_invoice_detail)
    if not success:
        Exceptions.register_not_found("Invoice Detail", id_invoice_detail)
    return {"message": "InvoiceDetail deleted successfully"}


@invoice_detail.get("/by_brand/{id_invoice}", response_model=List[InvoiceDetailByBrand])
def get_invoice_detail_by_brand_and_id_invoice(id_invoice: int, db: Session = Depends(get_db)):
    result = crud.get_invoice_detail_by_brand_and_id_invoice(db, id_invoice)
    return result
