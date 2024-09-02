# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import StoreType, StoreTypeCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

store_type = APIRouter(
    prefix="/storeType",
    tags=["StoreType"],
)

@store_type.get("/{id_store_type}", response_model=StoreType)
def get_storeType_by_id(id_store_type: int, db: Session = Depends(get_db)):
    """
    Show a Store Type

    This path operation shows a store type in the app.

    Parameters:
    - Register path parameter
        - store_type_id: int

    Returns a JSON with the store type:
    - id_store_type: int
    - store_type_name: str
    """
    db_storeType = crud.get_storeType_by_id(db, id_store_type)
    if db_storeType is None:
        Exceptions.register_not_found("StoreType", id_store_type)
    return db_storeType

@store_type.get("/", response_model=List[StoreType])
def get_storeTypes(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show storeTypes

    This path operation shows a list of storeTypes in the app with a limit on the number of storeTypes.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of storeTypes to retrieve (default: 10)

    Returns a JSON with a list of storeTypes in the app.
    """
    return crud.get_storeTypes(db, skip=skip, limit=limit)

@store_type.post("/", response_model=StoreType)
def create_storeType(storeType: StoreTypeCreate, db: Session = Depends(get_db)):
    """
    Create a Store Type

    This path operation creates a new store type in the app.

    Parameters:
    - Request body parameter
        - store_type: StoreTypeCreate -> A JSON object containing the following key:
            - store_type_name: str

    Returns a JSON with the newly created store type:
    - id_store_type: int
    - store_type_name: str
    """
    return crud.create_storeType(db, storeType)


@store_type.put("/{id_store_type}", response_model=StoreType)
def update_storeType(id_store_type: int, storeType: StoreTypeCreate, db: Session = Depends(get_db)):
    """
    Update a StoreType

    This path operation updates an existing storeType in the app.

    Parameters:
    - Register path parameter
        - storeType_id: int
    - Request body parameter
        - storeType: StoreTypeCreate -> A JSON object containing the updated storeType data:
            - storeType_name: str

    Returns a JSON with the updated storeType:
    - id_store_type: int
    - storeType_name: str
    """
    db_storeType = crud.update_storeType(db, id_store_type, storeType)
    if db_storeType is None:
        Exceptions.register_not_found("StoreType", id_store_type)
    return db_storeType

@store_type.delete("/{id_store_type}")
def delete_storeType(id_store_type: int, db: Session = Depends(get_db)):
    """
    Delete a StoreType

    This path operation deletes a storeType from the app.

    Parameters:
    - Register path parameter
        - storeType_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_storeType(db, id_store_type)
    if not success:
        Exceptions.register_not_found("StoreType", id_store_type)
    return {"message": "StoreType deleted successfully"}
