# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, Numeric, Enum, DateTime
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

# APP
from app.db import Base
from app.core import Gender


class Reference(Base):
    __tablename__ = "product_references"

    id_reference = Column(Integer, primary_key=True, index=True)
    reference = Column(String(100), unique=True, index=True, nullable=False)
    id_brand = Column(Integer, ForeignKey("brands.id_brand"), nullable=False)
    description = Column(String(500), nullable=True)
    gender = Column(Enum(Gender), nullable=False)
    value_base = Column(Numeric(12, 2), nullable=False)
    id_collection = Column(
        Integer, ForeignKey("collections.id_collection"), nullable=True
    )
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    brand = relationship("Brand", back_populates="references")
    collection = relationship("Collection", back_populates="references")
    actual_costs = relationship("ActualCost", back_populates="reference")
    order_details = relationship("OrderDetail", back_populates="reference")
    invoice_details = relationship("InvoiceDetail", back_populates="reference")
