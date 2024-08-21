# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Brand(Base):
    __tablename__ = "brands"

    id_brand = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"))
    brand_name = Column(String(100))

    line = relationship("Line", back_populates="brands")

