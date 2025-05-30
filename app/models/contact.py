# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Date, Boolean,
    Enum
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base
from app.core import Gender


class Contact(Base):
    __tablename__ = "contacts"

    id_contact = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    document = Column(Float, unique=True, index=True, nullable=False)
    gender = Column(Enum(Gender), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    id_role = Column(Integer, ForeignKey("roles.id_role"))
    birth_date = Column(Date)
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    relevant_details = Column(String(1000))
    active = Column(Boolean)

    customer = relationship("Customer", back_populates="contacts")
    role = relationship("Role", back_populates="contacts")
    city = relationship("City", back_populates="contacts")
