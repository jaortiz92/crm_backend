# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Date, Boolean
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class User(Base):
    __tablename__ = "users"

    id_user = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(500), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    document = Column(Float, nullable=False)
    id_role = Column(Integer, ForeignKey("roles.id_role"))
    email = Column(String(100), nullable=False)
    phone = Column(String(20))
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    birth_date = Column(Date)
    active = Column(Boolean)

    role = relationship("Role", back_populates="users")
    city = relationship("City", back_populates="users")