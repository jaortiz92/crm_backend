# Python
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

# App
from app.schemas import Invoice, InvoiceCreate, InvoiceFull, InvoiceWithDetail, User
from app import get_db
from app.core.auth import get_current_user
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


@invoice.get("/{id_invoice}/details", response_model=InvoiceWithDetail)
def get_invoice_by_id_with_details(id_invoice: int, db: Session = Depends(get_db)):
    """
    Show an Invoice

    This path operation shows an invoice in the app.

    Parameters:
    - Register path parameter
        - invoice_id: int

    Returns a JSON with the invoice with datails
    """
    db_invoice = crud.get_invoice_by_id_with_details(db, id_invoice)
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
def get_invoices(
    skip: int = 0, limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_type: str = Depends(crud.get_me_access_type)
):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices(db, current_user.id_user, access_type, skip=skip, limit=limit)


@invoice.get("/full/", response_model=List[InvoiceFull])
def get_invoices_full(
    skip: int = 0, limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_type: str = Depends(crud.get_me_access_type)
):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices(db, current_user.id_user, access_type, skip=skip, limit=limit)


@invoice.get("/customer_trip/{id_customer_trip}", response_model=List[InvoiceFull])
def get_invoices_by_customer_trip(
    id_customer_trip,
    db: Session = Depends(get_db)
):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices_by_customer_trip(db, id_customer_trip)


@invoice.get("/order/{id_order}", response_model=List[InvoiceFull])
def get_invoices_by_order(
    id_order,
    db: Session = Depends(get_db)
):
    """
    Show invoices

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of invoices to retrieve (default: 10)

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices_by_order(db, id_order)


@invoice.get("/customer/{id_customer}", response_model=List[InvoiceFull])
def get_invoices_by_customer(
    id_customer,
    db: Session = Depends(get_db)
):
    """
    Show invoices

    This path operation shows a list of invoices with the id_customer.

    Parameters:
    - Query parameters:
        - id_customer: int - Id customer

    Returns a JSON with a list of invoices in the app.
    """
    return crud.get_invoices_by_customer(db, id_customer)


@invoice.get("/query/", response_model=List[InvoiceFull])
def get_invoices_query(
    invoice_number: Optional[str] = None,
    key: Optional[int] = None,
    date_ge: Optional[date] = None,
    date_le: Optional[date] = None,
    id_order: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Show invoice

    This path operation shows a list of invoices in the app with a limit on the number of invoices.

    Parameters:
    - Query parameters:
        - invoice_number: str = None
        - key: int = None
        - date_ge: date = None
        - date_le: date = None
        - id_order: int = None

    Returns a JSON with a list of invoice in the app.
    """
    db_invoice = crud.get_invoices_query(
        db,
        invoice_number,
        key,
        date_ge,
        date_le,
        id_order
    )
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
    db_invoice = crud.create_invoice(db, invoice)
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
