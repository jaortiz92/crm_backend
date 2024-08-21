# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Date
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Contact(Base):
    __tablename__ = "contacts"

    id_contact = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    document = Column(Float, nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    id_store_type = Column(Integer, ForeignKey("store_types.id_store_type"))
    id_role = Column(Integer, ForeignKey("roles.id_role"))
    birth_date = Column(Date)

    customer = relationship("Customer", back_populates="contacts")
    store_type = relationship("StoreType", back_populates="contacts")
    role = relationship("Role", back_populates="contacts")
