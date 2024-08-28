# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date, Text, Boolean
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Task(Base):
    __tablename__ = "tasks"

    id_task = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_creator = Column(Integer, ForeignKey("users.id_user"))
    id_responsible = Column(Integer, ForeignKey("users.id_user"))
    creation_date = Column(Date, nullable=False)
    task = Column(Text, nullable=False)
    completed = Column(Boolean, default=False)
    closing_date = Column(Date)
    comment = Column(Text)

    customer = relationship("Customer", back_populates="tasks")
    creator_tasks = relationship("User", foreign_keys=[id_creator], back_populates="creator_tasks")
    responsible_task = relationship("User", foreign_keys=[id_responsible], back_populates="responsible_tasks")
