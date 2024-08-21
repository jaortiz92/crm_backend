# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, Boolean
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class ActivityType(Base):
    __tablename__ = "activity_types"

    id_activity_type = Column(Integer, primary_key=True, index=True)
    activity = Column(String(100), nullable=False)
    mandatory = Column(Boolean, nullable=False)
    activity_order = Column(Integer, nullable=False)
