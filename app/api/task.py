# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Task, TaskCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

task = APIRouter(
    prefix="/task",
    tags=["Task"],
)

@task.get("/{id_task}", response_model=Task)
def get_task(id_task: int, db: Session = Depends(get_db)):
    """
    Show a Task

    This path operation shows a task in the app.

    Parameters:
    - Register path parameter
        - id_task: int

    Returns a JSON with the task:
    - id_task: int
    - id_customer: int
    - id_creator_user: int
    - id_responsible_user: int
    - creation_date: date
    - task_description: str
    - completed: Optional[bool]
    - closing_date: Optional[date]
    - comment: Optional[str]
    """
    db_task = crud.get_task_by_id(db, id_task)
    if db_task is None:
        Exceptions.register_not_found("Task", id_task)
    return db_task

@task.get("/", response_model=List[Task])
def get_tasks(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show task

    This path operation shows a list of tasks in the app with a limit on the number of tasks.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of task to retrieve (default: 10)

    Returns a JSON with a list of task in the app.
    """
    return crud.get_tasks(db, skip=skip, limit=limit)

@task.post("/", response_model=Task)
def create_task(task: TaskCreate, db: Session = Depends(get_db)):
    """
    Create a Task

    This path operation creates a new task in the app.

    Parameters:
    - Request body parameter
        - task: TaskCreate -> A JSON object containing the following keys:
            - id_customer: int
            - id_creator_user: int
            - id_responsible_user: int
            - creation_date: date
            - task_description: str
            - completed: Optional[bool]
            - closing_date: Optional[date]
            - comment: Optional[str]

    Returns a JSON with the newly created task:
    - id_task: int
    - id_customer: int
    - id_creator_user: int
    - id_responsible_user: int
    - creation_date: date
    - task_description: str
    - completed: Optional[bool]
    - closing_date: Optional[date]
    - comment: Optional[str]
    """
    return crud.create_task(db, task)

@task.put("/{id_task}", response_model=Task)
def update_task(id_task: int, task: TaskCreate, db: Session = Depends(get_db)):
    """
    Update a Task

    This path operation updates an existing task in the app.

    Parameters:
    - Register path parameter
        - id_task: int
    - Request body parameter
        - task: TaskCreate -> A JSON object containing the updated task data:
            - id_customer: int
            - id_creator_user: int
            - id_responsible_user: int
            - creation_date: date
            - task_description: str
            - completed: Optional[bool]
            - closing_date: Optional[date]
            - comment: Optional[str]

    Returns a JSON with the updated task:
    - id_task: int
    - id_customer: int
    - id_creator_user: int
    - id_responsible_user: int
    - creation_date: date
    - task_description: str
    - completed: Optional[bool]
    - closing_date: Optional[date]
    - comment: Optional[str]
    """
    db_task = crud.update_task(db, id_task, task)
    if db_task is None:
        Exceptions.register_not_found("Task", id_task)
    return db_task

@task.delete("/{id_task}")
async def delete_task(id_task: int, db: Session = Depends(get_db)):
    """
    Delete a Task

    This path operation deletes a task from the app.

    Parameters:
    - Register path parameter
        - id_task: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_task(db, id_task)
    if not success:
        Exceptions.register_not_found("Task", id_task)
    return {"message": "Task deleted successfully"}