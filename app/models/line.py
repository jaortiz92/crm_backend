# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Line(Base):
    __tablename__ = "lines"

    id_line = Column(Integer, primary_key=True, index=True)
    line_name = Column(String(100))

    brand = relationship("Brand", back_populates="lines")
    collection = relationship("Collection", back_populates="lines")