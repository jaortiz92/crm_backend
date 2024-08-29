# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, Boolean
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class ActivityType(Base):
    __tablename__ = "activity_types"

    id_activity_type = Column(Integer, primary_key=True, index=True)
    activity = Column(String(100), unique=True, index=True, nullable=False)
    mandatory = Column(Boolean, nullable=False)
    activity_order = Column(Integer, nullable=False)

    activities = relationship("Activity", back_populates="activity_type")
