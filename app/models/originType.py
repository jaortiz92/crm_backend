# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class OriginType(Base):
    __tablename__ = "origin_types"

    id_origin_type = Column(Integer, primary_key=True, index=True)
    origin_type = Column(String(100), unique=True, index=True)
    description = Column(String(100), nullable=False)

    customers = relationship("Customer", back_populates="origin_type")
