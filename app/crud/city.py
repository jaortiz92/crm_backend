# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

# App
from app.models.city import City as CityModel
from app.schemas.city import City as CitySchema


def get_city_by_id(db: Session, id_city: int) -> CityModel:
    result = db.query(CityModel).filter(
        CityModel.id_city == id_city).first()
    return result


def get_cities(db: Session, skip: int = 0, limit: int = 10) -> list[CityModel]:
    return db.query(CityModel).offset(skip).limit(limit).all()


def get_cities_by_id_department(db: Session, id_department) -> list[CityModel]:
    return db.query(CityModel).filter(CityModel.id_department == id_department).all()


def get_cities_by_name(db: Session, city_name: str) -> list[CityModel]:
    search_pattern = f"%{city_name}%"
    return db.query(CityModel).filter(
        CityModel.city_name.ilike(search_pattern)).all()


def get_city_by_id_with_department(db: Session, city_id: int) -> CityModel:
    return db.query(CityModel).options(
        joinedload(CityModel.department)
    ).filter(CityModel.id_city == city_id).first()
