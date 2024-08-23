# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Date, Boolean,
    Enum
)
from sqlalchemy.orm import relationship

# APP
from db import Base
from core import Gender

class User(Base):
    __tablename__ = "users"

    id_user = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(500), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    document = Column(Float, nullable=False)
    gender = Column(Enum(Gender), nullable=False)  # 'M', 'F', 'U'
    id_role = Column(Integer, ForeignKey("roles.id_role"))
    email = Column(String(100), nullable=False)
    phone = Column(String(20))
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    birth_date = Column(Date)
    active = Column(Boolean)

    role = relationship("Role", back_populates="users")
    city = relationship("City", back_populates="users")

    customer = relationship("Customer", back_populates="users")
    Activity = relationship("Activity", back_populates="users")
    order = relationship("Order", back_populates="users")
    creator = relationship("Creator", back_populates="users")
    responsible = relationship("Responsible", back_populates="users")
    customerTrip = relationship("CustomerTrip", back_populates="users")
