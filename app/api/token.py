# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from jose import JWTError, jwt

# App
from app.schemas import Token, UserBaseOut
from app import get_db
import app.crud as crud
from app.core.auth import oauth2_scheme, SECRET_KEY, ALGORITHM
from app.api.utils import Exceptions

token = APIRouter(
    prefix="/login",
    tags=["login"],
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            Exceptions.credentials_exception()
    except JWTError:
        Exceptions.credentials_exception()
    user = crud.get_user_by_username(db ,username)
    if user is None:
        Exceptions.credentials_exception()
    return user


@token.post("/", response_model=Token)
def login(username: str, password: str, db: Session = Depends(get_db)):
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


@token.get("/me/", response_model=UserBaseOut)
def read_user_me(current_user: UserBaseOut = Depends(get_current_user)):
    return current_user
