# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Order(Base):
    __tablename__ = "orders"

    id_order = Column(Integer, primary_key=True, index=True)
    id_customer_trip = Column(Integer, ForeignKey(
        "customer_trips.id_customer_trip")
    )
    id_seller = Column(Integer, ForeignKey("users.id_user"))
    date_order = Column(Date, nullable=False)
    id_payment_method = Column(Integer, ForeignKey(
        "payment_methods.id_payment_method")
    )
    total_quantities = Column(Integer, nullable=False)
    system_quantities = Column(Integer)
    total_without_tax = Column(Integer, nullable=False)
    total_with_tax = Column(Integer, nullable=False)
    delivery_date = Column(Date, nullable=False)

    customer_trip = relationship("CustomerTrip", back_populates="orders")
    seller = relationship("User", back_populates="orders")
    payment_method = relationship("PaymentMethod", back_populates="orders")

    invoices = relationship("Invoice", back_populates="order")
    advances = relationship("Advance", back_populates="order")
    order_details = relationship("OrderDetail", back_populates="order")
