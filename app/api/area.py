from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional

from app.schemas import Area, AreaCreate, User
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

area = APIRouter(
    prefix="/area",
    tags=["Area"],
)


@area.get("/{id_area}", response_model=Area)
def get_area_by_id(
    id_area: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_area = crud.get_area_by_id(db, id_area)
    if db_area is None:
        Exceptions.register_not_found("Area", id_area)
    return db_area


@area.get("/", response_model=List[Area])
def get_areas(
    id_management: Optional[int] = None,
    skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud.get_areas(db, id_management=id_management, skip=skip, limit=limit)


@area.post("/", response_model=Area)
def create_area(
    area: AreaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if area.area_code:
        existing = crud.get_area_by_code(db, area.area_code)
        if existing:
            Exceptions.register_already_registered("Area", area.area_code)
    if area.id_management is not None:
        mgmt = crud.get_management_by_id(db, area.id_management)
        if mgmt is None:
            Exceptions.register_not_found("Management", area.id_management)
    return crud.create_area(db, area)


@area.put("/{id_area}", response_model=Area)
def update_area(
    id_area: int, area: AreaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_area = crud.update_area(db, id_area, area)
    if db_area is None:
        Exceptions.register_not_found("Area", id_area)
    return db_area


@area.delete("/{id_area}")
def delete_area(
    id_area: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    success = crud.delete_area(db, id_area)
    if not success:
        Exceptions.register_not_found("Area", id_area)
    return {"message": "Area deleted successfully"}
