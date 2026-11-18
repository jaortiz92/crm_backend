from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Department(Base):
    __tablename__ = "departments"

    id_department = Column(Integer, primary_key=True, index=True)
    department_code = Column(String(2), unique=True, index=True)
    department_name = Column(String(80))
    id_zone = Column(Integer, ForeignKey("zones.id_zone"))

    zone = relationship("Zone", back_populates="departments")
    cities = relationship("City", back_populates="department")
