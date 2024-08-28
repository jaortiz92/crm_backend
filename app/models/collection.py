# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Collection(Base):
    __tablename__ = "collections"

    id_collection = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"))
    collection_name = Column(String(30), nullable=False)
    short_collection_name = Column(String(10), nullable=False)
    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)

    line = relationship("Line", back_populates="collections")
    
    customer_trips = relationship("CustomerTrip", back_populates="collection")