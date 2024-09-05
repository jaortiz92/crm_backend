# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import InvoiceDetail, InvoiceDetailCreate
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
    Show an InvoiceDetail

    This path operation shows an invoice_detail in the app.

    Parameters:
    - Register path parameter
        - invoice_detail_id: int

    Returns a JSON with the invoice_detail:
    - id_invoice_detail: int
    - invoice_detail_number: str
    - invoice_detail_date: date
    - id_order: int
    """
    db_invoice_detail = crud.get_invoice_detail_by_id(db, id_invoice_detail)
    if db_invoice_detail is None:
        Exceptions.register_not_found("Customes", id_invoice_detail)
    return db_invoice_detail

@invoice_detail.get("/", response_model=List[InvoiceDetail])
def get_invoice_details(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show invoice_details

    This path operation shows a list of invoice_details in the app with a limit on the number of invoice_details.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoice_details to retrieve (default: 10)

    Returns a JSON with a list of invoice_details in the app.
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


@invoice_detail.put("/{id_invoice_detail}", response_model=InvoiceDetail)
def update_invoice_detail(id_invoice_detail: int, invoice_detail: InvoiceDetailCreate, db: Session = Depends(get_db)):
    """
    Update an InvoiceDetail

    This path operation updates an existing invoice_detail in the app.

    Parameters:
    - Register path parameter
        - invoice_detail_id: int
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
    db_invoice_detail = crud.update_invoice_detail(db, id_invoice_detail, invoice_detail)
    if db_invoice_detail is None:
        Exceptions.register_not_found("Customes", id_invoice_detail)
    return db_invoice_detail

@invoice_detail.delete("/{id_invoice_detail}")
def delete_invoice_detail(id_invoice_detail: int, db: Session = Depends(get_db)):
    """
    Delete an InvoiceDetail

    This path operation deletes an invoice_detail from the app.

    Parameters:
    - Register path parameter
        - invoice_detail_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_invoice_detail(db, id_invoice_detail)
    if not success:
        Exceptions.register_not_found("Customes", id_invoice_detail)
    return {"message": "InvoiceDetail deleted successfully"}
