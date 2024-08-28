# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, 
    Float
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class City(Base):
    __tablename__ = "cities"

    id_city = Column(Integer, primary_key=True, index=True)
    id_department = Column(Integer, ForeignKey("departments.id_department"))
    city_code = Column(String(5), unique=True, index=True)
    city_name = Column(String(80))
    latitude = Column(Float)
    longitude = Column(Float)

    department = relationship("Department", back_populates="cities")

    customers = relationship("Customer", back_populates="city")
    contacts = relationship("Contact", back_populates="city")
    users = relationship("User", back_populates="city")