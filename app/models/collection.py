# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Collection(Base):
    __tablename__ = "collections"

    id_collection = Column(Integer, primary_key=True, index=True)
    id_brand = Column(Integer, ForeignKey("brands.id_brand"))
    collection_name = Column(String(30), nullable=False)
    short_collection_name = Column(String(10), nullable=False)
    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)

    brand = relationship("Brand", back_populates="collections")
