# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import (
    UserCreate, User, UserFull, UserBase,
    UserPasswordUpdate, UserPasswordResetRequest, UserPasswordReset
)
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions
from app.api.token import get_current_user

user = APIRouter(
    prefix="/user",
    tags=["User"],
)


@user.get("/{id_user}", response_model=User)
def get_user_by_id(id_user: int, db: Session = Depends(get_db)):
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
    db_user = crud.get_user_by_id(db, id_user)
    if db_user is None:
        Exceptions.register_not_found("User", id_user)
    return db_user


@user.get("/full/{id_user}", response_model=UserFull)
def get_user_by_id_full(id_user: int, db: Session = Depends(get_db)):
    """
    Show a User full

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
    - role: RoleBase
    - city: CityFull
    """
    db_user = crud.get_user_by_id(db, id_user)
    if db_user is None:
        Exceptions.register_not_found("User", id_user)
    return db_user


@user.get("/", response_model=List[User])
def get_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
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


@user.get("/full/", response_model=List[UserFull])
def get_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show Users full

    This path operation shows a list of users full in the app with a limit on the number of users.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of users to retrieve (default: 10)

    Returns a JSON with a list of users full in the app.
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

    Returns a JSON with the created user in the app.
    """
    success = crud.create_user(db, user)
    if isinstance(success, dict):
        value = 'username {} or document {:.0f}'.format(
            user.username, user.document
        )
        Exceptions.register_already_registered("User", value)
    else:
        return success


@user.put("/{id_user}", response_model=User)
def update_user(id_user: int, user: UserBase, db: Session = Depends(get_db)):
    """
    Update a User

    This path operation updates the details of a user in the app

    Parameters:
    - Register path parameter:
        - id_user: int - The ID of the user to be updated
    - Request body:
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

    Returns a JSON with the updated user in the app.
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
    db_user = crud.update_user(db, id_user, user)
    if db_user is None:
        Exceptions.register_not_found("User", id_user)
    return db_user


@user.delete("/{id_user}")
def delete_user(
    id_user: int,
    db: Session = Depends(get_db),
):
    """
    Delete a User

    This path operation deletes a user from the app

    Parameters:
    - Register path parameter:
        - id_user: int - The ID of the user to be deleted

    Returns a JSON with the deleted user in the app.
    """
    success = crud.delete_user(db, id_user)
    if not success:
        Exceptions.register_not_found("User", id_user)
    return {"message": "User deleted successfully"}


@user.put("/update_password/")
def update_password(
    password_data: UserPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update user password.
    """
    if crud.update_password(db, current_user.id_user, password_data):
        return {"message": "Updated"}
    else:
        Exceptions.register_not_found("User", current_user.id_user)


@user.post("/request-password-reset")
def request_password_reset(request_data: UserPasswordResetRequest, db: Session = Depends(get_db)):
    """
    Request a password reset by email.
    """
    return crud.request_password_reset(db, request_data.email)


@user.post("/reset-password")
def reset_password(reset_data: UserPasswordReset, db: Session = Depends(get_db)):
    """
    Reset password using a valid token.
    """
    return crud.reset_password(db, reset_data.token, reset_data.new_password)
