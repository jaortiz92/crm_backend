# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Photo, PhotoCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

photo = APIRouter(
    prefix="/photo",
    tags=["Photo"],
)


@photo.get("/{id_photo}", response_model=Photo)
def get_photo_by_id(id_photo: int, db: Session = Depends(get_db)):
    """
    Show a Photo

    This path operation shows a photo in the app

    Parameters:
    - Register path parameter
        - id_photo: int

    Returns a JSON with a photo in the app:
    - id_photo: int
    - id_customer: int
    - url_photo: string
    """
    db_photo = crud.get_photo_by_id(db, id_photo)
    if db_photo is None:
        Exceptions.register_not_found("Photo", id_photo)
    return db_photo


@photo.get("/", response_model=List[Photo])
def get_photos(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show photos

    This path operation shows a list of photos in the app with a limit on the number of photos.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of photos to retrieve (default: 10)

    Returns a JSON with a list of photos in the app.
    """
    return crud.get_photos(db, skip=skip, limit=limit)


@photo.get("/customer/{id_customer}", response_model=List[Photo])
def get_photo_by_customer(id_customer: str, db: Session = Depends(get_db)):
    """
    Show a Photo

    This path operation shows a photo in the app

    Parameters:
    - Register path parameter
        - id_customer: int

    Returns a JSON with a photo in the app:
    - id_photo: int
    - id_customer: int
    - url_photo: string
    """
    db_photo = crud.get_photo_by_customer(db, id_customer)
    return db_photo


@photo.post("/", response_model=Photo)
def create_photo(photo: PhotoCreate, db: Session = Depends(get_db)):
    """
    Create a Photo

    This path operation creates a new photo in the app.

    Parameters:
    - Request body parameter
        - photo: PhotoCreate -> A JSON object containing the following key:
            - id_customer: int
            - url_photo: string

    Returns a JSON with the newly created photo:
    - id_photo: int
    - id_customer: int
    - url_photo: string
    """
    return crud.create_photo(db, photo)


@photo.put("/{id_photo}", response_model=Photo)
def update_photo(id_photo: int, photo: PhotoCreate, db: Session = Depends(get_db)):
    """
    Update a Photo

    This path operation updates an existing photo in the app.

    Parameters:
    - Register path parameter
        - id_photo: int
    - Request body parameter
        - photo: PhotoCreate -> A JSON object containing the updated photo data:
            - id_customer: int
            - url_photo: string

    Returns a JSON with the newly created photo:
    - id_photo: int
    - id_customer: int
    - url_photo: string
    """
    db_photo = crud.update_photo(db, id_photo, photo)
    if db_photo is None:
        Exceptions.register_not_found("Photo", id_photo)
    return db_photo


@photo.delete("/{id_photo}")
def delete_photo(id_photo: int, db: Session = Depends(get_db)):
    """
    Delete a Photo

    This path operation deletes a photo from the app.

    Parameters:
    - Register path parameter
        - id_photo: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_photo(db, id_photo)
    if not success:
        Exceptions.register_not_found("Photo", id_photo)
    return {"message": "Photo deleted successfully"}
