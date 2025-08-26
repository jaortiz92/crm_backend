# Python
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import json
from app.settings import settings

# App
from app.api.utils import Exceptions
from app import crud
from app import get_db

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def create_access_token(data: dict, expires_delta: int = None):
    to_encode = data.copy()
    if expires_delta is None:
        expire = datetime.now(timezone.utc) + \
            timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = datetime.now(timezone.utc) + \
            timedelta(minutes=expires_delta)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            Exceptions.credentials_exception()
    except JWTError:
        Exceptions.credentials_exception()
    user = crud.get_user_by_username(db, username)
    if user is None:
        Exceptions.credentials_exception()
    return user


def get_current_user_by_email(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            Exceptions.credentials_exception()
    except JWTError:
        Exceptions.credentials_exception()
    user = crud.get_user_by_email(db, email)
    if user is None:
        Exceptions.credentials_exception()
    return user
