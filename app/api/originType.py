# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import OriginType, OriginTypeCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

origin_type = APIRouter(
    prefix="/originType",
    tags=["OriginType"],
)


@origin_type.get("/{id_origin_type}", response_model=OriginType)
def get_originType_by_id(id_origin_type: int, db: Session = Depends(get_db)):
    """
    Show a Origin Type

    This path operation shows a origin type in the app.

    Parameters:
    - Register path parameter
        - origin_type_id: int

    Returns a JSON with the origin type:
    - id_origin_type: int
    - origin_type_name: str
    """
    db_originType = crud.get_originType_by_id(db, id_origin_type)
    if db_originType is None:
        Exceptions.register_not_found("OriginType", id_origin_type)
    return db_originType


@origin_type.get("/", response_model=List[OriginType])
def get_originTypes(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show originTypes

    This path operation shows a list of originTypes in the app with a limit on the number of originTypes.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of originTypes to retrieve (default: 10)

    Returns a JSON with a list of originTypes in the app.
    """
    return crud.get_originTypes(db, skip=skip, limit=limit)


@origin_type.post("/", response_model=OriginType)
def create_originType(originType: OriginTypeCreate, db: Session = Depends(get_db)):
    """
    Create a Origin Type

    This path operation creates a new origin type in the app.

    Parameters:
    - Request body parameter
        - origin_type: OriginTypeCreate -> A JSON object containing the following key:
            - origin_type_name: str

    Returns a JSON with the newly created origin type:
    - id_origin_type: int
    - origin_type_name: str
    """
    return crud.create_originType(db, originType)


@origin_type.put("/{id_origin_type}", response_model=OriginType)
def update_originType(id_origin_type: int, originType: OriginTypeCreate, db: Session = Depends(get_db)):
    """
    Update a OriginType

    This path operation updates an existing originType in the app.

    Parameters:
    - Register path parameter
        - originType_id: int
    - Request body parameter
        - originType: OriginTypeCreate -> A JSON object containing the updated originType data:
            - originType_name: str

    Returns a JSON with the updated originType:
    - id_origin_type: int
    - originType_name: str
    """
    db_originType = crud.update_originType(db, id_origin_type, originType)
    if db_originType is None:
        Exceptions.register_not_found("OriginType", id_origin_type)
    return db_originType


@origin_type.delete("/{id_origin_type}")
def delete_originType(id_origin_type: int, db: Session = Depends(get_db)):
    """
    Delete a OriginType

    This path operation deletes a originType from the app.

    Parameters:
    - Register path parameter
        - originType_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_originType(db, id_origin_type)
    if not success:
        Exceptions.register_not_found("OriginType", id_origin_type)
    return {"message": "OriginType deleted successfully"}
