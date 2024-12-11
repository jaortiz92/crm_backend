# Python
from datetime import date
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.task import Task as TaskModel
from app.schemas.task import TaskCreate, Task as TaskSchema
from app.crud.utils import Constants


def create_task(db: Session, task: TaskCreate) -> TaskSchema:
    db_task = TaskModel(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def get_task_by_id(db: Session, id_task: int) -> list[TaskSchema]:
    return db.query(TaskModel).filter(TaskModel.id_task == id_task).first()


def get_tasks(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[TaskSchema]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(TaskModel).order_by(
            TaskModel.creation_date.desc()
        ).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        print(id_user)
        result = db.query(TaskModel).filter(
            (TaskModel.id_creator == id_user) |
            (TaskModel.id_responsible == id_user)
        ).order_by(
            TaskModel.creation_date.desc()
        ).offset(skip).limit(limit).all()
    return result


def get_tasks_query(
    db: Session,
    id_customer: int = None,
    id_creator: int = None,
    id_responsible: int = None,
    creation_date_ge: date = None,
    creation_date_le: date = None,
    completed: bool = None,
    execution_date_ge: date = None,
    execution_date_le: date = None,
) -> list[TaskSchema]:
    query = db.query(TaskModel)
    if id_customer is not None:
        query = query.filter(TaskModel.id_customer == id_customer)
    if id_creator is not None:
        query = query.filter(TaskModel.id_creator == id_creator)
    if id_responsible is not None:
        query = query.filter(TaskModel.id_responsible == id_responsible)
    if creation_date_ge is not None:
        query = query.filter(TaskModel.creation_date >= creation_date_ge)
    if creation_date_le is not None:
        query = query.filter(TaskModel.creation_date <= creation_date_le)
    if completed is not None:
        query = query.filter(TaskModel.completed == completed)
    if execution_date_ge is not None:
        query = query.filter(TaskModel.execution_date >= execution_date_ge)
    if execution_date_le is not None:
        query = query.filter(TaskModel.execution_date <= execution_date_le)
    return query.order_by(
        TaskModel.creation_date.desc()
    ).all()


def update_task(db: Session, id_task: int, task: TaskCreate) -> TaskSchema:
    db_task = db.query(TaskModel).filter(TaskModel.id_task == id_task).first()
    if db_task:
        for key, value in task.model_dump().items():
            setattr(db_task, key, value)
        db.commit()
        db.refresh(db_task)
    return db_task


def delete_task(db: Session, id_task: int) -> bool:
    db_task = db.query(TaskModel).filter(TaskModel.id_task == id_task).first()
    if db_task:
        db.delete(db_task)
        db.commit()
        return True
    return False
