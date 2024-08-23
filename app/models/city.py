# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, 
    Float
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class City(Base):
    __tablename__ = "cities"

    id_city = Column(Integer, primary_key=True, index=True)
    id_department = Column(Integer, ForeignKey("departments.id_department"))
    city_code = Column(String(5), unique=True, index=True)
    city_name = Column(String(80))
    latitude = Column(Float)
    longitude = Column(Float)

    department = relationship("Department", back_populates="cities")
    customer = relationship("Customer", back_populates="cities")
    contact = relationship("Contact", back_populates="cities")
    user = relationship("User", back_populates="cities")