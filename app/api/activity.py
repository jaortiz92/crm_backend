# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Activity, ActivityCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

activity = APIRouter(
    prefix="/activity",
    tags=["Activity"],
)


@activity.get("/{id_activity}", response_model=Activity)
def get_activity_by_id(id_activity: int, db: Session = Depends(get_db)):
    """
    Show an Activity

    This path operation shows an activity in the app.

    Parameters:
    - Register path parameter
        - id_activity: int

    Returns a JSON with the activity:
    - id_activity: int
    - id_customer_trip: int
    - id_activity_type: int
    - id_user: int
    - estimated_date: date
    - execution_date: Optional[date]
    - completed: Optional[bool]
    - comment: Optional[str]
    """
    db_activity = crud.get_activity_by_id(db, id_activity)
    if db_activity is None:
        Exceptions.register_not_found("Activity", id_activity)
    return db_activity


@activity.get("/", response_model=List[Activity])
def get_activities(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show activities

    This path operation shows a list of activities in the app with a limit on the number of activities.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of activities to retrieve (default: 10)

    Returns a JSON with a list of activities in the app.
    """
    return crud.get_activities(db, skip=skip, limit=limit)


@activity.get("/customer_trip/{id_customer_trip}", response_model=List[Activity])
def get_activities_by_id_customer_trip(id_customer_trip: int, db: Session = Depends(get_db)):
    """
    Show activities by customer trip

    This path operation shows a list of activities by customer trip.

    Parameters:
    - Register path parameter
        - id_customer_trip: int

    Returns a JSON with a list of activities by customer trip in the app.
    """
    return crud.get_activities_by_id_customer_trip(db, id_customer_trip)


@activity.get("/activity_type/{id_activity_type}", response_model=List[Activity])
def get_activities_by_id_activity_type(id_activity_type: int, db: Session = Depends(get_db)):
    """
    Show activities by activity type

    This path operation shows a list of activities by activity type.

    Parameters:
    - Register path parameter
        - id_activity_type: int

    Returns a JSON with a list of activities by activity type in the app.
    """
    return crud.get_activities_by_id_activity_type(db, id_activity_type)


@activity.post("/", response_model=Activity)
def create_activity(activity: ActivityCreate, db: Session = Depends(get_db)):
    """
    Create an Activity

    This path operation creates a new activity in the app.

    Parameters:
    - Request body parameter
        - activity: ActivityCreate -> A JSON object containing the following keys:
            - id_customer_trip: int
            - id_activity_type: int
            - id_user: int
            - estimated_date: date
            - execution_date: Optional[date]
            - completed: Optional[bool]
            - comment: Optional[str]

    Returns a JSON with the newly created activity:
    - id_activity: int
    - id_customer_trip: int
    - id_activity_type: int
    - id_user: int
    - estimated_date: date
    - execution_date: Optional[date]
    - completed: Optional[bool]
    - comment: Optional[str]
    """
    return crud.create_activity(db, activity)


@activity.put("/{id_activity}", response_model=Activity)
def update_activity(id_activity: int, activity: ActivityCreate, db: Session = Depends(get_db)):
    """
    Update an Activity

    This path operation updates an existing activity in the app.

    Parameters:
    - Register path parameter
        - id_activity: int
    - Request body parameter
        - activity: ActivityCreate -> A JSON object containing the updated activity data:
            - id_customer_trip: int
            - id_activity_type: int
            - id_user: int
            - estimated_date: date
            - execution_date: Optional[date]
            - completed: Optional[bool]
            - comment: Optional[str]

    Returns a JSON with the updated activity:
    - id_activity: int
    - id_customer_trip: int
    - id_activity_type: int
    - id_user: int
    - estimated_date: date
    - execution_date: Optional[date]
    - completed: Optional[bool]
    - comment: Optional[str]
    """
    db_activity = crud.update_activity(db, id_activity, activity)
    if db_activity is None:
        Exceptions.register_not_found("Activity", id_activity)
    return db_activity


@activity.delete("/{id_activity}")
def delete_activity(id_activity: int, db: Session = Depends(get_db)):
    """
    Delete an Activity

    This path operation deletes an activity from the app.

    Parameters:
    - Register path parameter
        - id_activity: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_activity(db, id_activity)
    if not success:
        Exceptions.register_not_found("Activity", id_activity)
    return {"message": "Activity deleted successfully"}
