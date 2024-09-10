# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Shipment, ShipmentCreate, ShipmentFull
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

shipment = APIRouter(
    prefix="/shipment",
    tags=["Shipment"],
)

@shipment.get("/{id_shipment}", response_model=Shipment)
def get_shipment_by_id(id_shipment: int, db: Session = Depends(get_db)):
    """
    Show a Shipment

    This path operation shows a shipment in the app.

    Parameters:
    - Register path parameter
        - id_shipment: int

    Returns a JSON with the shipment.
    - id_shipment: int
    - id_invoice: int
    - shipment_date: date
    - carrier: str
    - tracking_number: str
    - received_date: date
    - shipment_value: float
    - details: Optional[str]
    """
    db_shipment = crud.get_shipment_by_id(db, id_shipment)
    if db_shipment is None:
        Exceptions.register_not_found("Shipment", id_shipment)
    return db_shipment


@shipment.get("/full/{id_shipment}", response_model=ShipmentFull)
def get_shipment_by_id_full(id_shipment: int, db: Session = Depends(get_db)):
    """
    Show a Shipment full

    This path operation shows a shipment full in the app.

    Parameters:
    - Register path parameter
        - id_shipment: int

    Returns a JSON with the shipment.
    - id_shipment: int
    - id_invoice: int
    - shipment_date: date
    - carrier: str
    - tracking_number: str
    - received_date: date
    - shipment_value: float
    - details: Optional[str]
    - invoice: InvoiceBase
    """
    db_shipment = crud.get_shipment_by_id(db, id_shipment)
    if db_shipment is None:
        Exceptions.register_not_found("Shipment", id_shipment)
    return db_shipment


@shipment.get("/", response_model=List[Shipment])
def get_shipments(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show shipments

    This path operation shows a list of shipments in the app with a limit on the number of shipments.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of shipments to retrieve (default: 10)

    Returns a JSON with a list of shipments in the app.
    """
    return crud.get_shipments(db, skip=skip, limit=limit)


@shipment.get("/full/", response_model=List[ShipmentFull])
def get_shipments_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show shipments full

    This path operation shows a list of shipments full in the app with a limit on the number of shipments full.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of shipments full to retrieve (default: 10)

    Returns a JSON with a list of shipments full in the app.
    """
    return crud.get_shipments(db, skip=skip, limit=limit)


@shipment.post("/", response_model=Shipment)
def create_shipment(shipment: ShipmentCreate, db: Session = Depends(get_db)):
    """
    Create a Shipment

    This path operation creates a new shipment in the app.

    Parameters:
    - Request body parameter
        - shipment: ShipmentCreate -> A JSON object containing the following keys:
            - id_invoice: int
            - shipment_date: date
            - carrier: str
            - tracking_number: str
            - received_date: date
            - shipment_value: float
            - details: Optional[str]

    Returns a JSON with the newly created shipment.
    - id_shipment: int
    - id_invoice: int
    - shipment_date: date
    - carrier: str
    - tracking_number: str
    - received_date: date
    - shipment_value: float
    - details: Optional[str]
    """
    return crud.create_shipment(db, shipment)


@shipment.put("/{id_shipment}", response_model=Shipment)
def update_shipment(id_shipment: int, shipment: ShipmentCreate, db: Session = Depends(get_db)):
    """
    Update a Shipment

    This path operation updates an existing shipment in the app.

    Parameters:
    - Register path parameter
        - id_shipment: int
    - Request body parameter
        - shipment: ShipmentCreate -> A JSON object containing the updated shipment data.
            - id_invoice: int
            - shipment_date: date
            - carrier: str
            - tracking_number: str
            - received_date: date
            - shipment_value: float
            - details: Optional[str]

    Returns a JSON with the updated shipment.
    - id_shipment: int
    - id_invoice: int
    - shipment_date: date
    - carrier: str
    - tracking_number: str
    - received_date: date
    - shipment_value: float
    - details: Optional[str]
    """
    db_shipment = crud.update_shipment(db, id_shipment, shipment)
    if db_shipment is None:
        Exceptions.register_not_found("Shipment", id_shipment)
    return db_shipment


@shipment.delete("/{id_shipment}")
def delete_shipment(id_shipment: int, db: Session = Depends(get_db)):
    """
    Delete a Shipment

    This path operation deletes a shipment from the app.

    Parameters:
    - Register path parameter
        - id_shipment: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_shipment(db, id_shipment)
    if not success:
        Exceptions.register_not_found("Shipment", id_shipment)
    return {"message": "Shipment deleted successfully"}
