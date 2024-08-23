# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date, Text, Boolean
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Activity(Base):
    __tablename__ = "activities"

    id_activity = Column(Integer, primary_key=True, index=True)
    id_customer_trip = Column(Integer, ForeignKey("customer_trips.id_customer_trip"))
    id_activity_type = Column(Integer, ForeignKey("activity_types.id_activity_type"))
    id_user = Column(Integer, ForeignKey("users.id_user"))
    estimated_date = Column(Date, nullable=False)
    execution_date = Column(Date)
    completed = Column(Boolean, default=False)
    comment = Column(Text)

    customer_trip = relationship("CustomerTrip", back_populates="activities")
    activity_type = relationship("ActivityType", back_populates="activities")
    user = relationship("User", back_populates="activities")
