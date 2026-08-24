from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Zone(Base):
    __tablename__ = "zones"

    id_zone = Column(Integer, primary_key=True, index=True)
    zone_name = Column(String(80), nullable=False)
    zone_code = Column(String(10), unique=True, index=True, nullable=False)

    departments = relationship("Department", back_populates="zone")
    cost_centers = relationship("CostCenter", back_populates="zone")
