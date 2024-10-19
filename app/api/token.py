# Python
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from jose import JWTError, jwt

# App
from app.schemas import Token, User
from app import get_db
import app.crud as crud
from app.core.auth import get_current_user
from app.api.utils import Exceptions

token = APIRouter(
    prefix="/login",
    tags=["login"],
)


@token.post("/", response_model=Token)
def login(username: str, password: str,  response: Response, db: Session = Depends(get_db)):
    """
    Login a User

    This path operation login a user in the app

    Parameters:
    - Register path parameter:
        - username: str - The username of the user to be login
        - password: str - The password of the user to be login

    Returns a message
    """
    token = crud.login_user(db, username, password)
    if isinstance(token, dict):
        Exceptions.credentials_exception()
    return token


@token.get("/me/", response_model=User)
def read_user_me(current_user: User = Depends(get_current_user)):
    return current_user
