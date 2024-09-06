# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.department import Department as DepartmentModel
from app.schemas.department import Department as DepartmentSchema


def get_department_by_id(db: Session, id_department: int) -> DepartmentSchema:
    result = db.query(DepartmentModel).filter(
        DepartmentModel.id_department == id_department).first()
    return result


def get_departments(db: Session, skip: int = 0, limit: int = 10) -> list[DepartmentSchema]:
    return db.query(DepartmentModel).offset(skip).limit(limit).all()


def get_departments_by_name(db: Session, department_name: str) -> list[DepartmentSchema]:
    search_pattern = f"%{department_name}%"
    return db.query(DepartmentModel).filter(
        DepartmentModel.department_name.ilike(search_pattern)).all()
