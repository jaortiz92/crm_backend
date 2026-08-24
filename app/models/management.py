from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Management(Base):
    __tablename__ = "managements"

    id_management = Column(Integer, primary_key=True, index=True)
    management_name = Column(String(100), nullable=False)
    management_code = Column(String(10), unique=True, index=True)

    areas = relationship("Area", back_populates="management")
