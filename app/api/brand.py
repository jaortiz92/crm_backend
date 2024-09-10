# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Brand, BrandCreate, BrandFull
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

brand = APIRouter(
    prefix="/brand",
    tags=["Brand"],
)

@brand.get("/{id_brand}", response_model=Brand)
def get_brand_by_id(id_brand: int, db: Session = Depends(get_db)):
    """
    Show a Brand

    This path operation shows a brand in the app.

    Parameters:
    - Register path parameter
        - brand_id: int

    Returns a JSON with the brand:
    - id_brand: int
    - id_line: int
    - brand_name: str
    """
    db_brand = crud.get_brand_by_id(db, id_brand)
    if db_brand is None:
        Exceptions.register_not_found("Brand", id_brand)
    return db_brand

@brand.get("/full/{id_brand}", response_model=BrandFull)
def get_brand_by_id_full(id_brand: int, db: Session = Depends(get_db)):
    """
    Show a Brand full

    This path operation shows a brand in the app.

    Parameters:
    - Register path parameter
        - brand_id: int

    Returns a JSON with the brand full:
    - id_brand: int
    - id_line: int
    - brand_name: str
    - line: Line
    """
    db_brand = crud.get_brand_by_id(db, id_brand)
    if db_brand is None:
        Exceptions.register_not_found("Brand", id_brand)
    return db_brand

@brand.get("/", response_model=List[Brand])
def get_brands(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show brands

    This path operation shows a list of brands in the app with a limit on the number of brands.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of brands to retrieve (default: 10)

    Returns a JSON with a list of brands in the app.
    """
    return crud.get_brands(db, skip=skip, limit=limit)

@brand.get("/full/", response_model=List[BrandFull])
def get_brands_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show brands full 

    This path operation shows a list of brands full in the app with a limit on the number of brands full.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of brands full to retrieve (default: 10)

    Returns a JSON with a list of brands full in the app.
    """
    return crud.get_brands(db, skip=skip, limit=limit)

@brand.post("/", response_model=Brand)
def create_brand(brand: BrandCreate, db: Session = Depends(get_db)):
    """
    Create a Brand

    This path operation creates a new brand in the app.

    Parameters:
    - Request body parameter
        - brand: BrandCreate -> A JSON object containing the following key:
            - id_line: int
            - brand_name: str

    Returns a JSON with the newly created brand:
    - id_brand: int
    - id_line: int
    - brand_name: str
    """
    return crud.create_brand(db, brand)


@brand.put("/{id_brand}", response_model=Brand)
def update_brand(id_brand: int, brand: BrandCreate, db: Session = Depends(get_db)):
    """
    Update a Brand

    This path operation updates an existing brand in the app.

    Parameters:
    - Register path parameter
        - brand_id: int
    - Request body parameter
        - brand: BrandCreate -> A JSON object containing the updated brand data:
            - id_line: int
            - brand_name: str

    Returns a JSON with the updated brand:
    - id_brand: int
    - id_line: int
    - brand_name: str
    """
    db_brand = crud.update_brand(db, id_brand, brand)
    if db_brand is None:
        Exceptions.register_not_found("Brand", id_brand)
    return db_brand

@brand.delete("/{id_brand}")
def delete_brand(id_brand: int, db: Session = Depends(get_db)):
    """
    Delete a Brand

    This path operation deletes a brand from the app.

    Parameters:
    - Register path parameter
        - brand_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_brand(db, id_brand)
    if not success:
        Exceptions.register_not_found("Brand", id_brand)
    return {"message": "Brand deleted successfully"}
