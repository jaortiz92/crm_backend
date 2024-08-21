# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Role(Base):
    __tablename__ = "roles"

    id_role = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50))
    access_type = Column(String(10))