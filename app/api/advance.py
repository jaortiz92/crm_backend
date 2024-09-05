# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Advance, AdvanceCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

advance = APIRouter(
    prefix="/advance",
    tags=["Advance"],
)

@advance.get("/{id_advance}", response_model=Advance)
def get_advance_by_id(id_advance: int, db: Session = Depends(get_db)):
    """
    Show an Advance

    This path operation shows an advance in the app.

    Parameters:
    - Register path parameter
        - id_advance: int

    Returns a JSON with the advance.
    - id_order: int
    - payment_date: date
    - advance_type: float
    - amount: int
    - payment: Optional[int]
    - balance: Optional[int]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    - id_advance: int
    """
    db_advance = crud.get_advance_by_id(db, id_advance)
    if db_advance is None:
        Exceptions.register_not_found("Advance", id_advance)
    return db_advance

@advance.get("/", response_model=List[Advance])
def get_advances(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show advances

    This path operation shows a list of advances in the app with a limit on the number of advances.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of advances to retrieve (default: 10)

    Returns a JSON with a list of advances in the app.
    - id_order: int
    - payment_date: date
    - advance_type: float
    - amount: int
    - payment: Optional[int]
    - balance: Optional[int]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    - id_advance: int
    """
    return crud.get_advances(db, skip=skip, limit=limit)

@advance.post("/", response_model=Advance)
def create_advance(advance: AdvanceCreate, db: Session = Depends(get_db)):
    """
    Create an Advance

    This path operation creates a new advance in the app.

    Parameters:
    - Request body parameter
        - advance: AdvanceCreate -> A JSON object containing the following keys:
            - id_order: int
            - payment_date: date
            - advance_type: float
            - amount: int
            - payment: Optional[int]
            - balance: Optional[int]
            - paid: Optional[bool]
            - last_payment_date: Optional[date]

    Returns a JSON with the newly created advance.
    - id_order: int
    - payment_date: date
    - advance_type: float
    - amount: int
    - payment: Optional[int]
    - balance: Optional[int]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    - id_advance: int
    """
    return crud.create_advance(db, advance)


@advance.put("/{id_advance}", response_model=Advance)
def update_advance(id_advance: int, advance: AdvanceCreate, db: Session = Depends(get_db)):
    """
    Update an Advance

    This path operation updates an existing advance in the app.

    Parameters:
    - Register path parameter
        - id_advance: int
    - Request body parameter
        - advance: AdvanceCreate -> A JSON object containing the updated advance data.
            - id_order: int
            - payment_date: date
            - advance_type: float
            - amount: int
            - payment: Optional[int]
            - balance: Optional[int]
            - paid: Optional[bool]
            - last_payment_date: Optional[date]

    Returns a JSON with the updated advance.
    - id_order: int
    - payment_date: date
    - advance_type: float
    - amount: int
    - payment: Optional[int]
    - balance: Optional[int]
    - paid: Optional[bool]
    - last_payment_date: Optional[date]
    - id_advance: int
    """
    db_advance = crud.update_advance(db, id_advance, advance)
    if db_advance is None:
        Exceptions.register_not_found("Advance", id_advance)
    return db_advance

@advance.delete("/{id_advance}")
def delete_advance(id_advance: int, db: Session = Depends(get_db)):
    """
    Delete an Advance

    This path operation deletes an advance from the app.

    Parameters:
    - Register path parameter
        - id_advance: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_advance(db, id_advance)
    if not success:
        Exceptions.register_not_found("Advance", id_advance)
    return {"message": "Advance deleted successfully"}
