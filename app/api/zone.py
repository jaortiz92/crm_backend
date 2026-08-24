from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.schemas import Zone, ZoneCreate, User
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

zone = APIRouter(
    prefix="/zone",
    tags=["Zone"],
)


@zone.get("/{id_zone}", response_model=Zone)
def get_zone_by_id(
    id_zone: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_zone = crud.get_zone_by_id(db, id_zone)
    if db_zone is None:
        Exceptions.register_not_found("Zone", id_zone)
    return db_zone


@zone.get("/", response_model=List[Zone])
def get_zones(
    skip: int = 0, limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return crud.get_zones(db, skip=skip, limit=limit)


@zone.post("/", response_model=Zone)
def create_zone(
    zone: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = crud.get_zone_by_code(db, zone.zone_code)
    if existing:
        Exceptions.register_already_registered("Zone", zone.zone_code)
    return crud.create_zone(db, zone)


@zone.put("/{id_zone}", response_model=Zone)
def update_zone(
    id_zone: int, zone: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_zone = crud.update_zone(db, id_zone, zone)
    if db_zone is None:
        Exceptions.register_not_found("Zone", id_zone)
    return db_zone


@zone.delete("/{id_zone}")
def delete_zone(
    id_zone: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    success = crud.delete_zone(db, id_zone)
    if not success:
        Exceptions.register_not_found("Zone", id_zone)
    return {"message": "Zone deleted successfully"}
