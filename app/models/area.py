from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db import Base


class Area(Base):
    __tablename__ = "areas"

    id_area = Column(Integer, primary_key=True, index=True)
    area_name = Column(String(100), nullable=False)
    area_code = Column(String(10), unique=True, index=True)
    id_management = Column(Integer, ForeignKey("managements.id_management"))

    management = relationship("Management", back_populates="areas")
    cost_centers = relationship("CostCenter", back_populates="area")
