# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date, Float, Boolean
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Advance(Base):
    __tablename__ = "advances"

    id_advance = Column(Integer, primary_key=True, index=True)
    id_order = Column(Integer, ForeignKey("orders.id_order"))
    payment_date = Column(Date, nullable=False)
    advance_type = Column(Float, nullable=False)
    amount = Column(Integer, nullable=False)
    payment = Column(Integer, server_default="0")
    balance = Column(Integer)
    paid = Column(Boolean, server_default="False")
    last_payment_date = Column(Date)

    order = relationship("Order", back_populates="advances")
