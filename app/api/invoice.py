# Python
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

# App
from app.schemas import Invoice, InvoiceCreate, InvoiceFull
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

invoice = APIRouter(
    prefix="/invoice",
    tags=["Invoice"],
)


@invoice.get("/{id_invoice}", response_model=Invoice)
def get_invoice_by_id(id_invoice: int, db: Session = Depends(get_db)):
    """
    Show an Invoice

    This path operation shows an invoice in the app.

    Parameters:
    - Register path parameter
        - invoice_id: int

    Returns a JSON with the invoice:
    - id_invoice: int
    - invoice_number: str
    - invoice_date: date
    - id_order: int
    """
    db_invoice = crud.get_invoice_by_id(db, id_invoice)
    if db_invoice is None:
        Exceptions.register_not_found("Customes", id_invoice)
    return db_invoice


@invoice.get("/full/{id_invoice}", response_model=InvoiceFull)
def get_invoice_by_id_full(id_invoice: int, db: Session = Depends(get_db)):
    """
    Show an Invoice

    This path operation shows an invoice in the app.

    Parameters:
    - Register path parameter
        - invoice_id: int

    Returns a JSON with the invoice:
    - id_invoice: int
    - invoice_number: str
    - invoice_date: date
    - id_order: int
    - order: OrderFull
    """
    db_invoice = crud.get_invoice_by_id(db, id_invoice)
    if db_invoice is None:
        Exceptions.register_not_found("Customes", id_invoice)
    return db_invoice


@invoice.get("/", response_model=List[Invoice])
def get_invoices(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices(db, skip=skip, limit=limit)


@invoice.get("/full/", response_model=List[InvoiceFull])
def get_invoices_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices(db, skip=skip, limit=limit)


@invoice.get("/query/", response_model=List[InvoiceFull])
def get_invoices_query(
    id_customer: Optional[int] = None,
    id_creator: Optional[int] = None,
    id_responsible: Optional[int] = None,
    creation_date_ge: Optional[date] = None,
    creation_date_le: Optional[date] = None,
    completed: Optional[bool] = None,
    closing_date_ge: Optional[date] = None,
    closing_date_le: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    Show invoice

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - id_customer: int = None
        - id_creator: int = None
        - id_responsible: int = None
        - creation_date_ge: date = None
        - creation_date_le: date = None
        - completed: bool = None
        - closing_date_ge: date = None
        - closing_date_le: date = None

    Returns a JSON with a list of invoice in the app.
    """
    db_invoice = crud.get_invoices_query(
        db,
        id_customer,
        id_creator,
        id_responsible,
        creation_date_ge,
        creation_date_le,
        completed,
        closing_date_ge,
        closing_date_le,
    )
    if db_invoice is None:
        Exceptions.register_not_found("Customer", id_customer)
    return db_invoice


@invoice.post("/", response_model=Invoice)
def create_invoice(invoice: InvoiceCreate, db: Session = Depends(get_db)):
    """
    Create an Invoice

    This path operation creates a new invoice in the app.

    Parameters:
    - Request body parameter
        - invoice: InvoiceCreate -> A JSON object containing the following keys:
            - invoice_number: str
            - invoice_date: date
            - id_order: int

    Returns a JSON with the newly created invoice:
    - id_invoice: int
    - invoice_number: str
    - invoice_date: date
    - id_order: int
    """
    db_invoice =  crud.create_invoice(db, invoice)
    if isinstance(db_invoice, dict):
        if db_invoice["value_already_registered"]:
            Exceptions.register_already_registered(
                "Invoice", '{}-{}'.format(
                    invoice.invoice_number, invoice.key
                )
            )
        else:
            Exceptions.register_not_found("Order", invoice.id_order)
    return db_invoice


@invoice.put("/{id_invoice}", response_model=Invoice)
def update_invoice(id_invoice: int, invoice: InvoiceCreate, db: Session = Depends(get_db)):
    """
    Update an Invoice

    This path operation updates an existing invoice in the app.

    Parameters:
    - Register path parameter
        - invoice_id: int
    - Request body parameter
        - invoice: InvoiceCreate -> A JSON object containing the updated invoice data:
            - invoice_number: str
            - invoice_date: date
            - id_order: int

    Returns a JSON with the updated invoice:
    - id_invoice: int
    - invoice_number: str
    - invoice_date: date
    - id_order: int
    """
    db_invoice = crud.update_invoice(db, id_invoice, invoice)
    if db_invoice is None:
        Exceptions.register_not_found("Customes", id_invoice)
    return db_invoice


@invoice.delete("/{id_invoice}")
def delete_invoice(id_invoice: int, db: Session = Depends(get_db)):
    """
    Delete an Invoice

    This path operation deletes an invoice from the app.

    Parameters:
    - Register path parameter
        - invoice_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_invoice(db, id_invoice)
    if not success:
        Exceptions.register_not_found("Customes", id_invoice)
    return {"message": "Invoice deleted successfully"}
