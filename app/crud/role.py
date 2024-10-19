# Python
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session

# App
from app.models.role import Role as RoleModel
from app.schemas.role import Role as RoleSchema
from app.models.user import User
from app.core.auth import get_current_user


def get_role_by_id(db: Session, id_role: int) -> RoleSchema:
    result = db.query(RoleModel).filter(
        RoleModel.id_role == id_role).first()
    return result


def get_roles(db: Session, skip: int = 0, limit: int = 10) -> list[RoleSchema]:
    return db.query(RoleModel).offset(skip).limit(limit).all()


def get_role_by_name(db: Session, role_name: str) -> RoleSchema:
    result = db.query(RoleModel).filter(
        RoleModel.role_name == role_name).first()
    return result


def get_me_access_type(current_user: User = Depends(get_current_user)) -> str:
    if current_user:
        return current_user.role.access_type
    else:
        return None
