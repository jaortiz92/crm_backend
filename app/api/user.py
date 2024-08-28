# Python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import User, UserCreate
from app import get_db
import app.crud as crud

user = APIRouter(
    prefix="/user",
    tags=["User"],
)


@user.get("/{id_user}", response_model=User)
def show_user(id_user: int, db: Session = Depends(get_db)):
    """
    Show a User

    This path operation shows a user in the app

    Parameters:
    - Register path parameter
        - id_user: int

    Returns a JSON with a user in the app, with the following keys:
    - id_user: int
    - username: str
    - first_name: str
    - last_name: str
    - document: float
    - gender: Gender
    - id_role: int
    - email: str
    - phone: Optional[str]
    - id_city: int
    - birth_date: Optional[date]
    - active: bool
    """
    return crud.get_user_by_id(db, id_user)


@user.get("/", response_model=List[User])
def show_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show Users

    This path operation shows a list of users in the app with a limit on the number of users.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of users to retrieve (default: 10)

    Returns a JSON with a list of users in the app.
    """
    return crud.get_users(db, skip=skip, limit=limit)


@user.post("/", response_model=User)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Create a User

    This path operation creates a new user in the app

    Parameters:
    - Request body:
        - user: UserCreate - The schema containing the user details

    Returns a JSON with the created user in the app.
    """
    return crud.create_user(db, user)

@user.put("/users/{id_user}", response_model=User)
def update_user(id_user: int, user: UserCreate, db: Session = Depends(get_db)):
    """
    Update a User

    This path operation updates the details of a user in the app

    Parameters:
    - Register path parameter:
        - id_user: int - The ID of the user to be updated
    - Request body:
        - user: UserCreate - The schema containing the updated user details

    Returns a JSON with the updated user in the app.
    """
    return crud.update_user(db, id_user, user)

@user.delete("/users/{id_user}", response_model=User)
def delete_user(id_user: int, db: Session = Depends(get_db)):
    """
    Delete a User

    This path operation deletes a user from the app

    Parameters:
    - Register path parameter:
        - id_user: int - The ID of the user to be deleted

    Returns a JSON with the deleted user in the app.
    """
    return crud.delete_user(db, id_user)