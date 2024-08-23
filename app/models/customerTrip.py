# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Boolean, Text
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class CustomerTrip(Base):
    __tablename__ = "customer_trips"

    id_customer_trip = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_seller = Column(Integer, ForeignKey("users.id_user"))
    id_collection = Column(Integer, ForeignKey("collections.id_collection"))
    budget = Column(Float, nullable=False)
    ordered = Column(Boolean)
    comment = Column(Text)

    customer = relationship("customer", back_populates="customer_trips")
    seller = relationship("User", back_populates="customer_trips")
    collection = relationship("Collection", back_populates="customer_trips")

    customer_trip = relationship("CustomerTrip", back_populates="customer_trips")
    order = relationship("Order", back_populates="customer_trips")