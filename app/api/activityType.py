# Python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import ActivityType, ActivityTypeCreate, ActivityTypeBatchReorder
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


@activity_type.get("/mandatory/", response_model=List[ActivityType])
def get_activity_types_mandatory(db: Session = Depends(get_db)):
    """
    Show activities type mandatory

    This path operation shows a list of activities type in the app with a limit on the number of activities type.

    Parameters:

    Returns a JSON with a list of activities type in the app.
    """
    return crud.get_activity_types_mandatory(db)


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


@activity_type.put("/reorder/", response_model=List[ActivityType])
def batch_reorder_activity_types(
    reorder_data: ActivityTypeBatchReorder,
    db: Session = Depends(get_db)
):
    """
    Reordenar actividades obligatorias

    Recibe una lista de actividades con sus nuevos órdenes y las actualiza
    de forma atómica. Valida que no haya órdenes duplicados y que todas
    las actividades sean obligatorias.
    """
    orders = [item.activity_order for item in reorder_data.activities]
    if len(orders) != len(set(orders)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate activity_order values are not allowed"
        )

    for item in reorder_data.activities:
        activity = crud.get_activity_type_by_id(db, item.id_activity_type)
        if not activity:
            Exceptions.register_not_found("Activity type", item.id_activity_type)
        if not activity.mandatory:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Activity type {item.id_activity_type} is not mandatory"
            )

    result = crud.batch_reorder_mandatory_activities(
        db,
        [item.model_dump() for item in reorder_data.activities]
    )
    return result


@activity_type.delete("/{id_activity_type}")
def delete_activity_type(id_activity_type: int, db: Session = Depends(get_db)):
    """
    Eliminar actividad y renumerar si es obligatoria

    Si la actividad eliminada era obligatoria, renumera automáticamente
    las actividades restantes para mantener el orden consecutivo.
    """
    activity = crud.get_activity_type_by_id(db, id_activity_type)
    if not activity:
        Exceptions.register_not_found("Activity type", id_activity_type)

    deleted_order = activity.activity_order if activity.mandatory else None

    success = crud.delete_activity_type(db, id_activity_type)
    if not success['deleted']:
        if success['elimination_allow']:
            Exceptions.register_not_found("Activity type", id_activity_type)
        else:
            Exceptions.conflict_with_register(
                "Activity type", id_activity_type
            )

    if deleted_order:
        crud.renumber_mandatory_activities_after_delete(db, deleted_order)

    return {"message": "Activity type deleted successfully"}
