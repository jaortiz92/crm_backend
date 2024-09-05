# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Credit, CreditCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

credit = APIRouter(
    prefix="/credit",
    tags=["Credit"],
)

@credit.get("/{id_credit}", response_model=Credit)
def get_credit_by_id(id_credit: int, db: Session = Depends(get_db)):
    """
    Show a Credit

    This path operation shows a credit in the app.

    Parameters:
    - Register path parameter
        - id_credit: int

    Returns a JSON with the credit.
    - id_credit: int
    - id_invoice: int
    - term: int
    - credit_value: float
    - payment_value: float
    - balance: Optional[float]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    """
    db_credit = crud.get_credit_by_id(db, id_credit)
    if db_credit is None:
        Exceptions.register_not_found("Credit", id_credit)
    return db_credit

@credit.get("/", response_model=List[Credit])
def get_credits(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show credits

    This path operation shows a list of credits in the app with a limit on the number of credits.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of credits to retrieve (default: 10)

    Returns a JSON with a list of credits in the app.
    """
    return crud.get_credits(db, skip=skip, limit=limit)

@credit.post("/", response_model=Credit)
def create_credit(credit: CreditCreate, db: Session = Depends(get_db)):
    """
    Create a Credit

    This path operation creates a new credit in the app.

    Parameters:
    - Request body parameter
        - credit: CreditCreate -> A JSON object containing the following keys:
            - id_invoice: int
            - term: int
            - credit_value: float
            - payment_value: float
            - balance: Optional[float]
            - paid: Optional[bool]
            - last_payment_date: Optional[date]

    Returns a JSON with the newly created credit.
    - id_credit: int
    - id_invoice: int
    - term: int
    - credit_value: float
    - payment_value: float
    - balance: Optional[float]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    """
    return crud.create_credit(db, credit)


@credit.put("/{id_credit}", response_model=Credit)
def update_credit(id_credit: int, credit: CreditCreate, db: Session = Depends(get_db)):
    """
    Update a Credit

    This path operation updates an existing credit in the app.

    Parameters:
    - Register path parameter
        - id_credit: int
    - Request body parameter
        - credit: CreditCreate -> A JSON object containing the updated credit data.
            - id_invoice: int
            - term: int
            - credit_value: float
            - payment_value: float
            - balance: Optional[float]
            - paid: Optional[bool]
            - last_payment_date: Optional[date]

    Returns a JSON with the updated credit.
    - id_credit: int
    - id_invoice: int
    - term: int
    - credit_value: float
    - payment_value: float
    - balance: Optional[float]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    """
    db_credit = crud.update_credit(db, id_credit, credit)
    if db_credit is None:
        Exceptions.register_not_found("Credit", id_credit)
    return db_credit

@credit.delete("/{id_credit}")
def delete_credit(id_credit: int, db: Session = Depends(get_db)):
    """
    Delete a Credit

    This path operation deletes a credit from the app.

    Parameters:
    - Register path parameter
        - id_credit: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_credit(db, id_credit)
    if not success:
        Exceptions.register_not_found("Credit", id_credit)
    return {"message": "Credit deleted successfully"}
