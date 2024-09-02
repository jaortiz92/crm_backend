# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import RatingCategory, RatingCategoryCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

rating_category = APIRouter(
    prefix="/ratingCategory",
    tags=["RatingCategory"],
)

@rating_category.get("/{id_rating_category}", response_model=RatingCategory)
def get_ratingCategory_by_id(id_rating_category: int, db: Session = Depends(get_db)):
    """
    Show a Rating Category

    This path operation shows a rating category in the app.

    Parameters:
    - Register path parameter
        - rating_category_id: int

    Returns a JSON with the rating category:
    - id_rating_category: int
    - rating_category: str
    - level: int
    """
    db_ratingCategory = crud.get_ratingCategory_by_id(db, id_rating_category)
    if db_ratingCategory is None:
        Exceptions.register_not_found("RatingCategory", id_rating_category)
    return db_ratingCategory

@rating_category.get("/", response_model=List[RatingCategory])
def get_ratingCategorys(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show ratingCategorys

    This path operation shows a list of ratingCategorys in the app with a limit on the number of ratingCategorys.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of ratingCategorys to retrieve (default: 10)

    Returns a JSON with a list of ratingCategorys in the app.
    """
    return crud.get_ratingCategorys(db, skip=skip, limit=limit)

@rating_category.post("/", response_model=RatingCategory)
def create_ratingCategory(ratingCategory: RatingCategoryCreate, db: Session = Depends(get_db)):
    """
    Create a Rating Category

    This path operation creates a new rating category in the app.

    Parameters:
    - Request body parameter
        - rating_category: RatingCategoryCreate -> A JSON object containing the following key:
            - rating_category: str
            - level: int

    Returns a JSON with the newly created rating category:
    - id_rating_category: int
    - rating_category: str
    - level: int
    """
    return crud.create_ratingCategory(db, ratingCategory)


@rating_category.put("/{id_rating_category}", response_model=RatingCategory)
def update_ratingCategory(id_rating_category: int, ratingCategory: RatingCategoryCreate, db: Session = Depends(get_db)):
    """
    Update a Rating Category

    This path operation updates an existing rating category in the app.

    Parameters:
    - Register path parameter
        - rating_category_id: int
    - Request body parameter
        - rating_category: RatingCategoryCreate -> A JSON object containing the updated rating category data:
            - rating_category: str
            - level: int

    Returns a JSON with the updated rating category:
    - id_rating_category: int
    - rating_category: str
    - level: int
    """
    db_ratingCategory = crud.update_ratingCategory(db, id_rating_category, ratingCategory)
    if db_ratingCategory is None:
        Exceptions.register_not_found("RatingCategory", id_rating_category)
    return db_ratingCategory

@rating_category.delete("/{id_rating_category}")
def delete_ratingCategory(id_rating_category: int, db: Session = Depends(get_db)):
    """
    Delete a Rating Category

    This path operation deletes a rating category from the app.

    Parameters:
    - Register path parameter
        - rating_category_id: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_ratingCategory(db, id_rating_category)
    if not success:
        Exceptions.register_not_found("RatingCategory", id_rating_category)
    return {"message": "RatingCategory deleted successfully"}
