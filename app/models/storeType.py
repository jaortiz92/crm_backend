# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class StoreType(Base):
    __tablename__ = "store_types"

    id_store_type = Column(Integer, primary_key=True, index=True)
    store_type = Column(String(100), unique=True, index=True)

    customers = relationship("Customer", back_populates="store_type")