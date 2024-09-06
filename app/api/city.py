# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import City
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

city = APIRouter(
    prefix="/city",
    tags=["City"],
)


@city.get("/{id_city}", response_model=City)
def get_city_by_id(id_city: int, db: Session = Depends(get_db)):
    """
    Show a City

    This path operation shows a city in the app

    Parameters:
    - Register path parameter
        - id_city: int

    Returns a JSON with a city in the app:
    - id_city: int
    - id_department: int
    - city_code: string
    - city_name: string
    - latitude: float
    - longitude: float
    """
    db_city = crud.get_city_by_id(db, id_city)
    if db_city is None:
        Exceptions.register_not_found("City", id_city)
    return db_city


@city.get("/", response_model=List[City])
def get_cities(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show citys

    This path operation shows a list of citys in the app with a limit on the number of citys.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of citys to retrieve (default: 10)

    Returns a JSON with a list of citys in the app.
    """
    return crud.get_cities(db, skip=skip, limit=limit)


@city.get("/department/{id_department}", response_model=List[City])
def get_cities_by_id_department(id_department: int, db: Session = Depends(get_db)):
    """
    Show cities by department

    This path operation shows a list of citys by department in the app with a limit on the number of citys.

    Parameters:
    - Register path parameter
        - id_department: int

    Returns a JSON with a list of citys in the app.
    """
    return crud.get_cities_by_id_department(db, id_department)


@city.get("/name/{city_name}", response_model=List[City])
def get_cities_by_name(city_name: str, db: Session = Depends(get_db)):
    """
    Show cities

    This path operation shows a list of citys in the app with a limit on the number of cities.

    Parameters:
    - Query parameters:
        - city_name: string

    Returns a JSON with a list of citys in the app.
    """
    return crud.get_cities_by_name(
        db, city_name
    )


@city.get("/{id_city}/department", response_model=City)
def get_city_by_id_with_department(id_city: int, db: Session = Depends(get_db)):
    """
    Show a City

    This path operation shows a city in the app

    Parameters:
    - Register path parameter
        - id_city: int

    Returns a JSON with a city in the app:
    - id_city: int
    - id_department: int
    - city_code: string
    - city_name: string
    - latitude: float
    - longitude: float
    """
    db_city = crud.get_city_by_id_with_department(db, id_city)
    print(db_city.__dir__())
    if db_city is None:
        Exceptions.register_not_found("City", id_city)
    return db_city
