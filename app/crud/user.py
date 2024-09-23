# Python
from fastapi import HTTPException
from sqlalchemy.orm import Session

# App
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, User as UserSchema
from app.crud.utils import statusRequest
from app.core.hashing import get_password_hash, verify_password


def create_user(db: Session, user: UserCreate) -> UserModel:
    status = statusRequest()
    user.username = user.username.lower()
    user.password = get_password_hash(user.password)
    db_user = get_user_by_username(db, user.username)
    if db_user:
        status['user_already_registered'] = True
        return status
    
    db_user = get_user_by_document(db, user.document)
    if db_user:
        status['user_already_registered'] = True
        return status
    else:
        db_user = UserModel(**user.model_dump())
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        return db_user


def login_user(db: Session, username: str, password: str) -> str:
    db_user = get_user_by_username(db, username.lower())
    if db_user:
        result = verify_password(db_user.password, password)
        if result:
            return 'OK'
    return 'Not OK'


def get_user_by_id(db: Session, id_user: int) -> UserSchema:
    return db.query(UserModel).filter(UserModel.id_user == id_user).first()


def get_user_by_username(db: Session, username: str) -> UserSchema:
    return db.query(UserModel).filter(UserModel.username == username).first()


def get_user_by_document(db: Session, document: str) -> UserSchema:
    return db.query(UserModel).filter(UserModel.document == document).first()


def get_users(db: Session, skip: int = 0, limit: int = 10) -> list[UserSchema]:
    return db.query(UserModel).offset(skip).limit(limit).all()


def get_all_users(db: Session) -> list[UserModel]:
    return db.query(UserModel).all()


def update_user(db: Session, id_user: int, user: UserCreate) -> UserSchema:
    db_user = db.query(UserModel).filter(UserModel.id_user == id_user).first()
    if db_user:
        for key, value in user.model_dump(exclude_unset=True).items():
            setattr(db_user, key, value)
        db.commit()
        db.refresh(db_user)
    return db_user


def delete_user(db: Session, id_user: int) -> bool:
    db_user = db.query(UserModel).filter(UserModel.id_user == id_user).first()
    if db_user:
        db.delete(db_user)
        db.commit()
        return True
    return False
