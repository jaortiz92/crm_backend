# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, func,
    Date, Text, Boolean, Float
)
from sqlalchemy.orm import relationship
from datetime import date

# APP
from app.db import Base


class Activity(Base):
    __tablename__ = "activities"

    id_activity = Column(Integer, primary_key=True, index=True)
    id_customer_trip = Column(Integer, ForeignKey(
        "customer_trips.id_customer_trip")
    )
    id_activity_type = Column(Integer, ForeignKey(
        "activity_types.id_activity_type")
    )
    id_user = Column(Integer, ForeignKey("users.id_user"))
    creation_date = Column(Date, server_default=func.now(), nullable=False)
    estimated_date = Column(Date, nullable=False)
    execution_date = Column(Date)
    completed = Column(Boolean, server_default="False")
    budget = Column(Float, server_default="0")
    execution_value = Column(Float, server_default="0")
    budget_authorized = Column(Float, server_default="0")
    authorized = Column(Boolean, server_default="False")
    authorizer = Column(Integer, ForeignKey("users.id_user"))
    date_authorized = Column(Date)
    comment = Column(Text)

    customer_trip = relationship("CustomerTrip", back_populates="activities")
    activity_type = relationship("ActivityType", back_populates="activities")
    user_activities = relationship(
        "User", foreign_keys=[id_user], back_populates="user_activities"
    )
    authorizer_activities = relationship(
        "User", foreign_keys=[authorizer], back_populates="authorizer_activities"
    )
