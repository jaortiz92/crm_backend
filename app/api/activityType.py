# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import ActivityType, ActivityTypeCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

activity_type = APIRouter(
    prefix="/activity_type",
    tags=["ActivityType"],
)


@activity_type.get("/{id_activity_type}", response_model=ActivityType)
def get_activity_type_by_id(id_activity_type: int, db: Session = Depends(get_db)):
    """
    Show an Activity Type

    This path operation shows an activity type in the app.

    Parameters:
    - Register path parameter
        - id_activity_type: int

    Returns a JSON with the activity type:
    - id_activity_type: int
    - activity_name: str
    - mandatory: bool
    - activity_order: int
    """
    db_activity_type = crud.get_activity_type_by_id(db, id_activity_type)
    if db_activity_type is None:
        Exceptions.register_not_found("Activity type", id_activity_type)
    return db_activity_type


@activity_type.get("/", response_model=List[ActivityType])
def get_activity_types(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show activities type

    This path operation shows a list of activities type in the app with a limit on the number of activities type.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of activities type to retrieve (default: 10)

    Returns a JSON with a list of activities type in the app.
    """
    return crud.get_activity_types(db, skip=skip, limit=limit)


@activity_type.post("/", response_model=ActivityType)
def create_activity_type(activity_type: ActivityTypeCreate, db: Session = Depends(get_db)):
    """
    Create an Activity Type

    This path operation creates a new activity type in the app.

    Parameters:
    - Request body parameter
        - activity_type: ActivityTypeCreate -> A JSON object containing the following keys:
            - activity_name: str
            - mandatory: bool
            - activity_order: int

    Returns a JSON with the newly created activity type:
    - id_activity_type: int
    - activity_name: str
    - mandatory: bool
    - activity_order: int
    """
    return crud.create_activity_type(db, activity_type)


@activity_type.put("/{id_activity_type}", response_model=ActivityType)
def update_activity_type(id_activity_type: int, activity_type: ActivityTypeCreate, db: Session = Depends(get_db)):
    """
    Update an Activity Type

    This path operation updates an existing activity type in the app.

    Parameters:
    - Register path parameter
        - id_activity_type: int
    - Request body parameter
        - activity_type: ActivityTypeCreate -> A JSON object containing the updated activity type data:
            - activity_name: str
            - mandatory: bool
            - activity_order: int

    Returns a JSON with the updated activity type:
    - id_activity_type: int
    - activity_name: str
    - mandatory: bool
    - activity_order: int
    """
    db_activity_type = crud.update_activity_type(
        db, id_activity_type, activity_type)
    if db_activity_type is None:
        Exceptions.register_not_found("Activity type", id_activity_type)
    return db_activity_type


@activity_type.delete("/{id_activity_type}")
def delete_activity_type(id_activity_type: int, db: Session = Depends(get_db)):
    """
    Delete an Activity Type

    This path operation deletes an activity type from the app.

    Parameters:
    - Register path parameter
        - id_activity_type: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_activity_type(db, id_activity_type)
    if not success['deleted']:
        if success['alimination_allow']:
            Exceptions.register_not_found("Activity type", id_activity_type)
        else:
            Exceptions.conflict_with_register(
                "Activity type", id_activity_type
            )

    return {"message": "Activity type deleted successfully"}
