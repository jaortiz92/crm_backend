# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class StoreType(Base):
    __tablename__ = "store_types"

    id_store_type = Column(Integer, primary_key=True, index=True)
    store_type = Column(String(100))
