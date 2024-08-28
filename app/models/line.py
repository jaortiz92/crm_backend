# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Line(Base):
    __tablename__ = "lines"

    id_line = Column(Integer, primary_key=True, index=True)
    line_name = Column(String(100))

    brands = relationship("Brand", back_populates="line")
    collections = relationship("Collection", back_populates="line")