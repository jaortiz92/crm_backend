# Python
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import json

# App
from app.api.utils import Exceptions
from app import crud
from app import get_db

info = open("./app/core/configToken.json")
info = json.load(info)

SECRET_KEY = info["SECRET_KEY"]
ALGORITHM = info["ALGORITHM"]
ACCESS_TOKEN_EXPIRE_MINUTES = info["ACCESS_TOKEN_EXPIRE_MINUTES"]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + \
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
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
