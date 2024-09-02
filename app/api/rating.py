# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Rating, RatingCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

rating = APIRouter(
    prefix="/rating",
    tags=["Rating"],
)

@rating.get("/{id_rating}", response_model=Rating)
def get_rating_by_id(id_rating: int, db: Session = Depends(get_db)):
    """
    Show a Rating

    This path operation shows a rating in the app.

    Parameters:
    - Register path parameter
        - rating_id: int

    Returns a JSON with the rating:
    - id_rating: int
    - id_line: int
    - rating_name: str
    """
    db_rating = crud.get_rating_by_id(db, id_rating)
    if db_rating is None:
        Exceptions.register_not_found("Rating", id_rating)
    return db_rating

@rating.get("/", response_model=List[Rating])
def get_ratings(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show ratings

    This path operation shows a list of ratings in the app with a limit on the number of ratings.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of ratings to retrieve (default: 10)

    Returns a JSON with a list of ratings in the app.
    """
    return crud.get_ratings(db, skip=skip, limit=limit)

@rating.post("/", response_model=Rating)
def create_rating(rating: RatingCreate, db: Session = Depends(get_db)):
    """
    Create a Rating

    This path operation creates a new rating in the app.

    Parameters:
    - Request body parameter
        - rating: RatingCreate -> A JSON object containing the following key:
            - id_line: int
            - rating_name: str

    Returns a JSON with the newly created rating:
    - id_rating: int
    - id_line: int
    - rating_name: str
    """
    return crud.create_rating(db, rating)


@rating.put("/{id_rating}", response_model=Rating)
def update_rating(id_rating: int, rating: RatingCreate, db: Session = Depends(get_db)):
    """
    Update a Rating

    This path operation updates an existing rating in the app.

    Parameters:
    - Register path parameter
        - rating_id: int
    - Request body parameter
        - rating: RatingCreate -> A JSON object containing the updated rating data:
            - id_line: int
            - rating_name: str

    Returns a JSON with the updated rating:
    - id_rating: int
    - id_line: int
    - rating_name: str
    """
    db_rating = crud.update_rating(db, id_rating, rating)
    if db_rating is None:
        Exceptions.register_not_found("Rating", id_rating)
    return db_rating

@rating.delete("/{id_rating}")
def delete_rating(id_rating: int, db: Session = Depends(get_db)):
    """
    Delete a Rating

    This path operation deletes a rating from the app.

    Parameters:
    - Register path parameter
        - rating_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_rating(db, id_rating)
    if not success:
        Exceptions.register_not_found("Rating", id_rating)
    return {"message": "Rating deleted successfully"}
