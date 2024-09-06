# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Role
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

role = APIRouter(
    prefix="/role",
    tags=["Role"],
)


@role.get("/{id_role}", response_model=Role)
def get_role_by_id(id_role: int, db: Session = Depends(get_db)):
    """
    Show a Role

    This path operation shows a role in the app

    Parameters:
    - Register path parameter
        - id_role: int

    Returns a JSON with a role in the app:
    - id_role: int
    - role_name: string
    - access_type: string
    """
    db_role = crud.get_role_by_id(db, id_role)
    if db_role is None:
        Exceptions.register_not_found("Role", id_role)
    return db_role


@role.get("/", response_model=List[Role])
def get_roles(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show roles

    This path operation shows a list of roles in the app with a limit on the number of roles.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of roles to retrieve (default: 10)

    Returns a JSON with a list of roles in the app.
    """
    return crud.get_roles(db, skip=skip, limit=limit)


@role.get("/name/{role_name}", response_model=Role)
def get_role_by_name(role_name: str, db: Session = Depends(get_db)):
    """
    Show a Role

    This path operation shows a role in the app

    Parameters:
    - Register path parameter
        - role_name: string

    Returns a JSON with a role in the app:
    - id_role: int
    - role_name: string
    - access_type: string
    """
    db_role = crud.get_role_by_name(db, role_name)
    if db_role is None:
        Exceptions.register_not_found("Role", role_name)
    return db_role
