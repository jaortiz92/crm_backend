from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.schemas import Management, ManagementCreate, User
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

management = APIRouter(
    prefix="/management",
    tags=["Management"],
)


@management.get("/{id_management}", response_model=Management)
def get_management_by_id(
    id_management: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_management = crud.get_management_by_id(db, id_management)
    if db_management is None:
        Exceptions.register_not_found("Management", id_management)
    return db_management


@management.get("/", response_model=List[Management])
def get_managements(
    skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud.get_managements(db, skip=skip, limit=limit)


@management.post("/", response_model=Management)
def create_management(
    management: ManagementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if management.management_code:
        existing = crud.get_management_by_code(db, management.management_code)
        if existing:
            Exceptions.register_already_registered("Management", management.management_code)
    return crud.create_management(db, management)


@management.put("/{id_management}", response_model=Management)
def update_management(
    id_management: int, management: ManagementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_management = crud.update_management(db, id_management, management)
    if db_management is None:
        Exceptions.register_not_found("Management", id_management)
    return db_management


@management.delete("/{id_management}")
def delete_management(
    id_management: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    success = crud.delete_management(db, id_management)
    if not success:
        Exceptions.register_not_found("Management", id_management)
    return {"message": "Management deleted successfully"}
