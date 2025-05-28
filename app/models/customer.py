# Python
from datetime import date, datetime
# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Boolean

)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Customer(Base):
    __tablename__ = "customers"

    id_customer = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(100), nullable=False)
    document = Column(Float, unique=True, index=True, nullable=False)
    email = Column(String(100), nullable=True)
    phone = Column(String(20))
    id_store_type = Column(Integer, ForeignKey("store_types.id_store_type"))
    address = Column(String(255), nullable=True)
    # id_brand = Column(Integer, ForeignKey("brands.id_brand"))
    id_seller = Column(Integer, ForeignKey("users.id_user"))
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    stores = Column(Integer)
    credit_limit = Column(Float, server_default="0")
    with_documents = Column(Boolean, server_default="False")
    active = Column(Boolean, server_default="True")
    relevant_details = Column(String(1000))
    social_media = Column(String(1000))

    store_type = relationship("StoreType", back_populates="customers")
    # brand = relationship("Brand", back_populates="customers")
    seller = relationship("User", back_populates="customers")
    city = relationship("City", back_populates="customers")

    customer_trips = relationship("CustomerTrip", back_populates="customer")
    contacts = relationship("Contact", back_populates="customer")
    tasks = relationship("Task", back_populates="customer")
    ratings = relationship("Rating", back_populates="customer")
    customer_brands = relationship(
        "CustomerBrand",
        back_populates="customer",
        overlaps="brands"
    )
    brands = relationship(
        "Brand",
        secondary="customer_brands",
        back_populates="customers",
        overlaps="customer_brands"
    )
    photos = relationship("Photo", back_populates="customer")
