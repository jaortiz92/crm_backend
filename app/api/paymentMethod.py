# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import PaymentMethod
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

payment_method = APIRouter(
    prefix="/payment_method",
    tags=["PaymentMethod"],
)


@payment_method.get("/{id_payment_method}", response_model=PaymentMethod)
def get_payment_method_by_id(id_payment_method: int, db: Session = Depends(get_db)):
    """
    Show a PaymentMethod

    This path operation shows a payment_method in the app

    Parameters:
    - Register path parameter
        - id_payment_method: int

    Returns a JSON with a payment_method in the app:
    - id_payment_method: int
    - payment_method_name: string
    """
    db_payment_method = crud.get_payment_method_by_id(db, id_payment_method)
    if db_payment_method is None:
        Exceptions.register_not_found("PaymentMethod", id_payment_method)
    return db_payment_method


@payment_method.get("/", response_model=List[PaymentMethod])
def get_payment_methods(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show payment_methods

    This path operation shows a list of payment_methods in the app with a limit on the number of payment_methods.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of payment_methods to retrieve (default: 10)

    Returns a JSON with a list of payment_methods in the app.
    """
    return crud.get_payment_methods(db, skip=skip, limit=limit)


@payment_method.get("/name/{payment_method_name}", response_model=List[PaymentMethod])
def get_payments_method_by_name(payment_method_name: str, db: Session = Depends(get_db)):
    """
    Show payment methods

    This path operation shows a list of payment_methods in the app with a limit on the number of payment_methods.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of payment_methods to retrieve (default: 10)

    Returns a JSON with a list of payment_methods in the app.
    """
    return crud.get_payments_method_by_name(
        db, payment_method_name
    )
