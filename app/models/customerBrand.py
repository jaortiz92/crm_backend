# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class CustomerBrand(Base):
    __tablename__ = "customer_brands"

    id_customer_brand = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_brand = Column(Integer, ForeignKey("brands.id_brand"))

    customer = relationship(
        "Customer",
        back_populates="customer_brands",
        overlaps="brands,customers"
    )
    brand = relationship(
        "Brand",
        back_populates="customer_brands",
        overlaps="brands,customers"
    )
