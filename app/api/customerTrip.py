# Python
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import CustomerTrip, CustomerTripCreate, CustomerTripFull, User
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

customer_trip = APIRouter(
    prefix="/customer_trip",
    tags=["CustomerTrip"],
)


@customer_trip.get("/{id_customer_trip}", response_model=CustomerTrip)
async def get_customer_trip_by_id(id_customer_trip: int, db: Session = Depends(get_db)):
    """
    Show a Customer Trip

    This path operation shows a customer trip in the app.

    Parameters:
    - Register path parameter
        - id_customer_trip: int

    Returns a JSON with the customer trip:
    - id_customer_trip: int
    - id_customer: int
    - id_seller: int
    - id_collection: int
    - budget: float
    - closed: Optional[bool]
    - comment: Optional[str]
    """
    db_customer_trip = crud.get_customer_trip_by_id(db, id_customer_trip)
    if db_customer_trip is None:
        Exceptions.register_not_found("Customer Trip", id_customer_trip)
    return db_customer_trip


@customer_trip.get("/", response_model=List[CustomerTrip])
def get_customer_trips(
    skip: int = 0, limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_type: str = Depends(crud.get_me_access_type)
):
    """
    Show customer trips

    This path operation shows a list of customer trips in the app with a limit on the number of customer trips.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of customer trips to retrieve (default: 10)

    Returns a JSON with a list of customer trips in the app.
    """
    return crud.get_customer_trips(db, current_user.id_user, access_type, skip=skip, limit=limit)


@customer_trip.get("/full/{id_customer_trip}", response_model=CustomerTripFull)
async def get_customer_trip_full_by_id(id_customer_trip: int, db: Session = Depends(get_db)):
    """
    Show a Customer Trip

    This path operation shows a customer trip in the app.

    Parameters:
    - Register path parameter
        - id_customer_trip: int

    Returns a JSON with the customer trip:
    - id_customer_trip: int
    - id_customer: int
    - id_seller: int
    - id_collection: int
    - budget: float
    - closed: Optional[bool]
    - comment: Optional[str]
    """
    db_customer_trip = crud.get_customer_trip_by_id(db, id_customer_trip)
    if db_customer_trip is None:
        Exceptions.register_not_found("Customer Trip", id_customer_trip)
    return db_customer_trip


@customer_trip.get("/full/", response_model=List[CustomerTripFull])
def get_customer_trips_full(
    skip: int = 0, limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    access_type: str = Depends(crud.get_me_access_type)
):
    """
    Show customer trips

    This path operation shows a list of customer trips in the app with a limit on the number of customer trips.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of customer trips to retrieve (default: 10)

    Returns a JSON with a list of customer trips in the app.
    """
    return crud.get_customer_trips(db, current_user.id_user, access_type, skip=skip, limit=limit)


@customer_trip.get("/full/customer/{id_customer}", response_model=List[CustomerTripFull])
async def get_customer_trips_by_id_customer(id_customer: int, db: Session = Depends(get_db)):
    """
    Show customer trips

    This path operation shows a list of customer trips by id_customer

    Parameters:
    - Query parameters:
        - id_customer: int - The id_customer


    Returns a JSON with a list of customer trips in the app.
    """
    db_customer_trip = crud.get_customer_trips_by_id_customer(db, id_customer)
    return db_customer_trip


@customer_trip.post("/", response_model=CustomerTrip)
async def create_customer_trip(customer_trip: CustomerTripCreate, db: Session = Depends(get_db)):
    """
    Create a Customer Trip

    This path operation creates a new customer trip in the app.

    Parameters:
    - Request body parameter
        - customer_trip: CustomerTripCreate -> A JSON object containing the following keys:
            - id_customer: int
            - id_seller: int
            - id_collection: int
            - budget: float
            - closed: Optional[bool]
            - comment: Optional[str]

    Returns a JSON with the newly created customer trip:
    - id_customer_trip: int
    - id_customer: int
    - id_seller: int
    - id_collection: int
    - budget: float
    - closed: Optional[bool]
    - comment: Optional[str]
    """
    return crud.create_customer_trip(db, customer_trip)


@customer_trip.put("/{id_customer_trip}", response_model=CustomerTrip)
async def update_customer_trip(id_customer_trip: int, customer_trip: CustomerTripCreate, db: Session = Depends(get_db)):
    """
    Update a Customer Trip

    This path operation updates an existing customer trip in the app.

    Parameters:
    - Register path parameter
        - id_customer_trip: int
    - Request body parameter
        - customer_trip: CustomerTripCreate -> A JSON object containing the updated customer trip data:
            - id_customer: int
            - id_seller: int
            - id_collection: int
            - budget: float
            - closed: Optional[bool]
            - comment: Optional[str]

    Returns a JSON with the updated customer trip:
    - id_customer_trip: int
    - id_customer: int
    - id_seller: int
    - id_collection: int
    - budget: float
    - closed: Optional[bool]
    - comment: Optional[str]
    """
    db_customer_trip = crud.update_customer_trip(
        db, id_customer_trip, customer_trip)
    if db_customer_trip is None:
        Exceptions.register_not_found("Customer Trip", id_customer_trip)
    return db_customer_trip


@customer_trip.post("/file/customerTripsTemplate/create")
async def create_customers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('xlsx', 'xlsm')):
        Exceptions.conflict_with_register('File Format', file.filename)
    result = await crud.create_or_update_customer_trips(db, file, create=True)
    if result:
        return {"message": result}
    else:
        return Exceptions.conflict_with_register('File', file.filename)


@customer_trip.post("/file/customerTripsTemplate/update")
async def update_customers(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('xlsx', 'xlsm')):
        Exceptions.conflict_with_register('File Format', file.filename)
    result = await crud.create_or_update_customer_trips(db, file, create=False)
    if result:
        return {"message": result}
    else:
        return Exceptions.conflict_with_register('File', file.filename)


@customer_trip.delete("/{id_customer_trip}")
async def delete_customer_trip(id_customer_trip: int, db: Session = Depends(get_db)):
    """
    Delete a Customer Trip

    This path operation deletes a customer trip from the app.

    Parameters:
    - Register path parameter
        - id_customer_trip: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_customer_trip(db, id_customer_trip)
    if not success:
        Exceptions.register_not_found("Customer Trip", id_customer_trip)
    return {"message": "Customer Trip deleted successfully"}
