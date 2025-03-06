# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Role(Base):
    __tablename__ = "roles"

    id_role = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), unique=True, index=True)
    access_type = Column(String(10))

    contacts = relationship("Contact", back_populates="role")
    users = relationship("User", back_populates="role")
