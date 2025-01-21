# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Brand(Base):
    __tablename__ = "brands"

    id_brand = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"))
    brand_name = Column(String(100), unique=True, index=True)

    line = relationship("Line", back_populates="brands")

    customers = relationship("Customer", back_populates="brand")
    invoice_details = relationship("InvoiceDetail", back_populates="brand")
    order_details = relationship("OrderDetail", back_populates="brand")
    customer_brands = relationship(
        "CustomerBrand",
        back_populates="brand",
        overlaps="customers"
    )
    customers = relationship(
        "Customer",
        secondary="customer_brands",
        back_populates="brands",
        overlaps="customer_brands"
    )
