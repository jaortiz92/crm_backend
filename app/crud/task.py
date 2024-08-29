# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.task import Task as TaskModel
from app.schemas.task import TaskCreate, Task as TaskSchema


def create_task(db: Session, task: TaskCreate) -> TaskSchema:
    db_task = TaskModel(**task.model_dump())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

def get_task_by_id(db: Session, task_id: int) -> list[TaskSchema]:
    return db.query(TaskModel).filter(TaskModel.id_task == task_id).first()

def get_tasks(db: Session, skip: int = 0, limit: int = 10) -> list[TaskSchema]:
    return db.query(TaskModel).order_by(
        TaskModel.creation_date.desc()
    ).offset(skip).limit(limit).all()

def update_task(db: Session, task_id: int, task: TaskCreate) -> TaskSchema:
    db_task = db.query(TaskModel).filter(TaskModel.id_task == task_id).first()
    if db_task:
        for key, value in task.model_dump().items():
            setattr(db_task, key, value)
        db.commit()
        db.refresh(db_task)
    return db_task

def delete_task(db: Session, task_id: int) -> bool:
    db_task = db.query(TaskModel).filter(TaskModel.id_task == task_id).first()
    if db_task:
        db.delete(db_task)
        db.commit()
        return True
    return False