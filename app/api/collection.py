# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Collection, CollectionCreate, CollectionFull
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

collection = APIRouter(
    prefix="/collection",
    tags=["Collection"],
)

@collection.get("/{id_collection}", response_model=Collection)
def get_collection_by_id(id_collection: int, db: Session = Depends(get_db)):
    """
    Show a Collection

    This path operation shows a collection in the app.

    Parameters:
    - Register path parameter
        - collection_id: int

    Returns a JSON with the collection:
    - id_collection: int
    - id_line: int
    - collection_name: str
    - short_collection_name: str
    - year: int
    - quarter: int
    """
    db_collection = crud.get_collection_by_id(db, id_collection)
    if db_collection is None:
        Exceptions.register_not_found("Collection", id_collection)
    return db_collection


@collection.get("/full/{id_collection}", response_model=CollectionFull)
def get_collection_by_id_full(id_collection: int, db: Session = Depends(get_db)):
    """
    Show a Collection full

    This path operation shows a collection in the app.

    Parameters:
    - Register path parameter
        - collection_id: int

    Returns a JSON with the collection:
    - id_collection: int
    - id_line: int
    - collection_name: str
    - short_collection_name: str
    - year: int
    - quarter: int
    - line: LineBase
    """
    db_collection = crud.get_collection_by_id(db, id_collection)
    if db_collection is None:
        Exceptions.register_not_found("Collection", id_collection)
    return db_collection


@collection.get("/", response_model=List[Collection])
def get_collections(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show collections

    This path operation shows a list of collections in the app with a limit on the number of collections.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of collections to retrieve (default: 10)

    Returns a JSON with a list of collections in the app.
    """
    return crud.get_collections(db, skip=skip, limit=limit)


@collection.get("/full/", response_model=List[CollectionFull])
def get_collections_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show collections full

    This path operation shows a list of collections full in the app with a limit on the number of collections full.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of collections to retrieve (default: 10)

    Returns a JSON with a list of collections full in the app.
    """
    return crud.get_collections(db, skip=skip, limit=limit)


@collection.post("/", response_model=Collection)
def create_collection(collection: CollectionCreate, db: Session = Depends(get_db)):
    """
    Create a Collection

    This path operation creates a new collection in the app.

    Parameters:
    - Request body parameter
        - collection: CollectionCreate -> A JSON object containing the following key:
            - id_line: int
            - collection_name: str
            - short_collection_name: str
            - year: int
            - quarter: int

    Returns a JSON with the newly created collection:
    - id_collection: int
    - id_line: int
    - collection_name: str
    - short_collection_name: str
    - year: int
    - quarter: int
    """
    return crud.create_collection(db, collection)


@collection.put("/{id_collection}", response_model=Collection)
def update_collection(id_collection: int, collection: CollectionCreate, db: Session = Depends(get_db)):
    """
    Update a Collection

    This path operation updates an existing collection in the app.

    Parameters:
    - Register path parameter
        - collection_id: int
    - Request body parameter
        - collection: CollectionCreate -> A JSON object containing the updated collection data:
            - id_line: int
            - collection_name: str
            - short_collection_name: str
            - year: int
            - quarter: int

    Returns a JSON with the updated collection:
    - id_collection: int
    - id_line: int
    - collection_name: str
    - short_collection_name: str
    - year: int
    - quarter: int
    """
    db_collection = crud.update_collection(db, id_collection, collection)
    if db_collection is None:
        Exceptions.register_not_found("Collection", id_collection)
    return db_collection


@collection.delete("/{id_collection}")
def delete_collection(id_collection: int, db: Session = Depends(get_db)):
    """
    Delete a Collection

    This path operation deletes a collection from the app.

    Parameters:
    - Register path parameter
        - collection_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_collection(db, id_collection)
    if not success:
        Exceptions.register_not_found("Collection", id_collection)
    return {"message": "Collection deleted successfully"}
