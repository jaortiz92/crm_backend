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
    budget_quantities = Column(Float, nullable=False)
    ordered = Column(Boolean)
    comment = Column(Text)

    customer = relationship("Customer", back_populates="customer_trips")
    seller = relationship("User", back_populates="customer_trips")
    collection = relationship("Collection", back_populates="customer_trips")

    orders = relationship("Order", back_populates="customer_trip")
    activities = relationship("Activity", back_populates="customer_trip")
