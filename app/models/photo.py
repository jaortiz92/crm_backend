# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Photo(Base):
    __tablename__ = "photos"

    id_photo = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    url_photo = Column(String(1000), nullable=False)

    customer = relationship("Customer", back_populates="photos")
