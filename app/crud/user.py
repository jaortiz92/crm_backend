# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, User as UserSchema


def create_user(db: Session, user: UserCreate) -> UserModel:
    db_user = UserModel(**user.model_dump())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_user_by_id(db: Session, user_id: int) -> UserModel:
    return db.query(UserModel).filter(UserModel.id_user == user_id).first()


def get_users(db: Session, skip: int = 0, limit: int = 10) -> list[UserModel]:
    return db.query(UserModel).offset(skip).limit(limit).all()


def get_all_users(db: Session) -> list[UserModel]:
    return db.query(UserModel).all()


def update_user(db: Session, user_id: int, user: UserCreate) -> UserSchema:
    db_user = db.query(UserModel).filter(UserModel.id_user == user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found"
        )
    for key, value in user.model_dump(exclude_unset=True).items():
        setattr(db_user, key, value)
    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> UserSchema:
    db_user = db.query(UserModel).filter(UserModel.id_user == user_id).first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found"
        )
    db.delete(db_user)
    db.commit()
    return db_user
