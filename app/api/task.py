# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date

# App
from app.schemas import Task, TaskCreate, TaskFull
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

task = APIRouter(
    prefix="/task",
    tags=["Task"],
)

@task.get("/{id_task}", response_model=Task)
def get_task_by_id(id_task: int, db: Session = Depends(get_db)):
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


@task.get("/full/{id_task}", response_model=TaskFull)
def get_task_by_id_full(id_task: int, db: Session = Depends(get_db)):
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



@task.get("/query/", response_model=List[TaskFull])
def get_tasks_query(
        id_customer: Optional[int] = None,
        id_creator: Optional[int] = None,
        id_responsible: Optional[int] = None,
        creation_date_ge: Optional[date] = None,
        creation_date_le: Optional[date] = None,
        completed: Optional[bool] = None,
        closing_date_ge: Optional[date] = None,
        closing_date_le: Optional[date] = None,
        db: Session = Depends(get_db)
    ):
    """
    Show task

    This path operation shows a list of tasks in the app with a limit on the number of tasks.

    Parameters:
    - Query parameters:
        - id_customer: int = None
        - id_creator: int = None
        - id_responsible: int = None
        - creation_date_ge: date = None
        - creation_date_le: date = None
        - completed: bool = None
        - closing_date_ge: date = None
        - closing_date_le: date = None

    Returns a JSON with a list of task in the app.
    """
    db_task = crud.get_tasks_query(
        db,
        id_customer,
        id_creator,
        id_responsible,
        creation_date_ge,
        creation_date_le,
        completed,
        closing_date_ge,
        closing_date_le,
    )
    if db_task is None:
        Exceptions.register_not_found("Customer", id_customer)
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


@task.get("/full/", response_model=List[TaskFull])
def get_tasks(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show task

    This path operation shows a list of tasks in the app with a limit on the number of tasks.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of task to retrieve (default: 10)

    Returns a JSON with a list of task full in the app.
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