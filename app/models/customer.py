# Python
from datetime import date, datetime
# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Boolean

)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Customer(Base):
    __tablename__ = "customers"

    id_customer = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(100), nullable=False)
    document = Column(Float, nullable=False)
    email = Column(String(100), nullable=False)
    phone = Column(String(20))
    id_store_type = Column(Integer, ForeignKey("store_types.id_store_type"))
    address = Column(String(255), nullable=False)
    id_brand = Column(Integer, ForeignKey("brands.id_brand"))
    id_seller = Column(Integer, ForeignKey("users.id_user"))
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    stores = Column(Integer)
    active = Column(Boolean)

    store_type = relationship("StoreType", back_populates="customers")
    brand = relationship("Brand", back_populates="customers")
    seller = relationship("User", back_populates="customers")
    city = relationship("City", back_populates="customers")

    customer_trip = relationship("CustomerTrip", back_populates="customers")
    contact = relationship("Contacts", back_populates="customers")
    task = relationship("Tasks", back_populates="customers")
    rating = relationship("Rating", back_populates="customers")
    