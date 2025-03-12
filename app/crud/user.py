# Python
from fastapi import HTTPException
from sqlalchemy.orm import Session

# App
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, UserBase, User as UserSchema, UserPasswordUpdate
from app.schemas.token import Token as TokenSchema
from app.crud.utils import statusRequest
from app.core.hashing import get_password_hash, verify_password
from app.core.auth import create_access_token, get_current_user_by_email
from app.utils.emails.emails import send_email_restore_password


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


def login_user(db: Session, username: str, password: str) -> TokenSchema:
    status = statusRequest()
    db_user = get_user_by_username(db, username.lower())
    if db_user:
        result = verify_password(db_user.password, password)
        if result:
            access_token = create_access_token(data={"sub": username})
            return TokenSchema(
                access_token=access_token,
                token_type="bearer"
            )
    return status


def get_user_by_id(db: Session, id_user: int) -> UserSchema:
    return db.query(UserModel).filter(UserModel.id_user == id_user).first()


def get_user_by_username(db: Session, username: str) -> UserSchema:
    return db.query(UserModel).filter(UserModel.username == username).first()


def get_user_by_document(db: Session, document: str) -> UserSchema:
    return db.query(UserModel).filter(UserModel.document == document).first()


def get_user_by_email(db: Session, email: str) -> UserSchema:
    return db.query(UserModel).filter(UserModel.email == email).first()


def get_users(db: Session, skip: int = 0, limit: int = 10) -> list[UserSchema]:
    return db.query(UserModel).offset(skip).limit(limit).all()


def get_all_users(db: Session) -> list[UserModel]:
    return db.query(UserModel).all()


def update_user(db: Session, id_user: int, user: UserBase) -> UserSchema:
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


def update_password(db: Session, id_user: int, password_data: UserPasswordUpdate) -> UserModel:
    status = statusRequest()
    db_user = db.query(UserModel).filter(UserModel.id_user == id_user).first()
    if not db_user:
        return status

    if not verify_password(db_user.password, password_data.current_password):
        return status

    db_user.password = get_password_hash(password_data.new_password)
    db.commit()
    db.refresh(db_user)
    return True


def request_password_reset(db: Session, email: str):
    status = statusRequest()
    db_user = db.query(UserModel).filter(UserModel.email == email).first()
    if not db_user:
        return status

    reset_token = create_access_token(data={"sub": email}, expires_delta=30)

    return send_email_restore_password(
        db_user.email,
        f"{db_user.first_name} {db_user.last_name}",
        reset_token
    )


def reset_password(db: Session, token: str, new_password: str):
    db_user: UserModel = get_current_user_by_email(token, db)
    db_user.password = get_password_hash(new_password)
    db.commit()
    db.refresh(db_user)
    return True
