# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base


class Department(Base):
    __tablename__ = "departments"

    id_department = Column(Integer, primary_key=True, index=True)
    department_code = Column(String(2), unique=True, index=True)
    department_name = Column(String(80))

