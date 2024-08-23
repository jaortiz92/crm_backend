# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Order(Base):
    __tablename__ = "orders"

    id_order = Column(Integer, primary_key=True, index=True)
    id_customer_trip = Column(Integer, ForeignKey("customer_trips.id_customer_trip"))
    id_seller = Column(Integer, ForeignKey("users.id_user"))
    date_order = Column(Date, nullable=False)
    id_payment_method = Column(Integer, ForeignKey("payment_methods.id_payment_method"))
    quantities = Column(Integer, nullable=False)
    system_quantities = Column(Integer)
    value_without_vat = Column(Integer, nullable=False)
    value_with_vat = Column(Integer, nullable=False)
    delivery_date = Column(Date, nullable=False)

    customer_trip = relationship("CustomerTrip", back_populates="orders")
    seller = relationship("User", back_populates="orders")
    payment_method = relationship("PaymentMethod", back_populates="orders")

    invoice = relationship("Invoice", back_populates="orders")
    advance = relationship("Advance", back_populates="orders")
