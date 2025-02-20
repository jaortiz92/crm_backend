# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Enum
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base
from app.core import Gender


class OrderDetail(Base):
    __tablename__ = "order_details"

    id_order_detail = Column(Integer, primary_key=True, index=True)
    id_order = Column(Integer, ForeignKey("orders.id_order"))
    product = Column(String(50), nullable=False)
    description = Column(String(50), nullable=False)
    color = Column(String(50), nullable=False)
    size = Column(String(50), nullable=False)
    id_brand = Column(Integer, ForeignKey("brands.id_brand"))
    gender = Column(Enum(Gender), nullable=False)  # 'M', 'F', 'U'
    unit_value = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    value_without_tax = Column(Float, nullable=False)
    value_with_tax = Column(Float, nullable=False)

    order = relationship("Order", back_populates="order_details")
    brand = relationship("Brand", back_populates="order_details")
