# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Date, Boolean,
    Enum, UniqueConstraint
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base
from app.core import Gender


class User(Base):
    __tablename__ = "users"

    id_user = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(500), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    document = Column(Float, unique=True, index=True, nullable=False)
    gender = Column(Enum(Gender), nullable=False)
    id_role = Column(Integer, ForeignKey("roles.id_role"), server_default="1")
    email = Column(String(100), nullable=False)
    phone = Column(String(20))
    id_city = Column(Integer, ForeignKey("cities.id_city"))
    birth_date = Column(Date)
    active = Column(Boolean, server_default="True")

    role = relationship("Role", back_populates="users")
    city = relationship("City", back_populates="users")

    customers = relationship("Customer", back_populates="seller")
    user_activities = relationship(
        "Activity", foreign_keys='Activity.id_user',
        back_populates="user_activities"
    )
    authorizer_activities = relationship(
        "Activity", foreign_keys='Activity.authorizer',
        back_populates="authorizer_activities"
    )
    orders = relationship("Order", back_populates="seller")
    creator_tasks = relationship(
        "Task", foreign_keys='Task.id_creator', back_populates="creator_tasks"
    )
    responsible_tasks = relationship(
        "Task", foreign_keys='Task.id_responsible', back_populates="responsible_task"
    )
    customer_trips = relationship("CustomerTrip", back_populates="seller")
