# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Line, LineCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

line = APIRouter(
    prefix="/line",
    tags=["Line"],
)

@line.get("/{id_line}", response_model=Line)
def get_line_by_id(id_line: int, db: Session = Depends(get_db)):
    """
    Show a Line

    This path operation shows a line in the app.

    Parameters:
    - Register path parameter
        - line_id: int

    Returns a JSON with the line:
    - id_line: int
    - line_name: str
    """
    db_line = crud.get_line_by_id(db, id_line)
    if db_line is None:
        Exceptions.register_not_found("Line", id_line)
    return db_line

@line.get("/", response_model=List[Line])
def get_lines(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show lines

    This path operation shows a list of lines in the app with a limit on the number of lines.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of lines to retrieve (default: 10)

    Returns a JSON with a list of lines in the app.
    """
    return crud.get_lines(db, skip=skip, limit=limit)

@line.post("/", response_model=Line)
def create_line(line: LineCreate, db: Session = Depends(get_db)):
    """
    Create a Line

    This path operation creates a new line in the app.

    Parameters:
    - Request body parameter
        - line: LineCreate -> A JSON object containing the following key:
            - line_name: str

    Returns a JSON with the newly created line:
    - id_line: int
    - line_name: str
    """
    return crud.create_line(db, line)


@line.put("/{id_line}", response_model=Line)
def update_line(id_line: int, line: LineCreate, db: Session = Depends(get_db)):
    """
    Update a Line

    This path operation updates an existing line in the app.

    Parameters:
    - Register path parameter
        - line_id: int
    - Request body parameter
        - line: LineCreate -> A JSON object containing the updated line data:
            - line_name: str

    Returns a JSON with the updated line:
    - id_line: int
    - line_name: str
    """
    db_line = crud.update_line(db, id_line, line)
    if db_line is None:
        Exceptions.register_not_found("Line", id_line)
    return db_line

@line.delete("/{id_line}")
def delete_line(id_line: int, db: Session = Depends(get_db)):
    """
    Delete a Line

    This path operation deletes a line from the app.

    Parameters:
    - Register path parameter
        - line_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_line(db, id_line)
    if not success:
        Exceptions.register_not_found("Line", id_line)
    return {"message": "Line deleted successfully"}
