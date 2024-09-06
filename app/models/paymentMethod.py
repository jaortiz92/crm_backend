# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id_payment_method = Column(Integer, primary_key=True, index=True)
    payment_method_name = Column(String(100), unique=True, index=True)

    orders = relationship("Order", back_populates="payment_method")
