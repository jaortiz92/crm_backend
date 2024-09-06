# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Department
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

department = APIRouter(
    prefix="/department",
    tags=["Department"],
)


@department.get("/{id_department}", response_model=Department)
def get_department_by_id(id_department: int, db: Session = Depends(get_db)):
    """
    Show a Department

    This path operation shows a department in the app

    Parameters:
    - Register path parameter
        - id_department: int

    Returns a JSON with a department in the app:
    - id_department: int
    - department_code: string
    - department_name: string
    """
    db_department = crud.get_department_by_id(db, id_department)
    if db_department is None:
        Exceptions.register_not_found("Department", id_department)
    return db_department


@department.get("/", response_model=List[Department])
def get_departments(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show departments

    This path operation shows a list of departments in the app with a limit on the number of departments.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of departments to retrieve (default: 10)

    Returns a JSON with a list of departments in the app.
    """
    return crud.get_departments(db, skip=skip, limit=limit)


@department.get("/name/{department_name}", response_model=List[Department])
def get_departments_by_name(department_name: str, db: Session = Depends(get_db)):
    """
    Show departments

    This path operation shows a list of departments in the app with a limit on the number of departments.

    Parameters:
    - Query parameters:
        - department_name: string

    Returns a JSON with a list of departments in the app.
    """
    return crud.get_departments_by_name(
        db, department_name
    )
