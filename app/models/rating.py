# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, func,
    Text, Date
)
from sqlalchemy.orm import relationship
from datetime import date

# APP
from app.db import Base


class Rating(Base):
    __tablename__ = "ratings"

    id_rating = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_rating_category = Column(Integer, ForeignKey(
        "rating_categories.id_rating_category"))
    date_updated = Column(Date, server_default=func.now(), nullable=False)
    id_creator = Column(Integer, ForeignKey("users.id_user"))
    comments = Column(Text)

    customer = relationship("Customer", back_populates="ratings")
    rating_category = relationship("RatingCategory", back_populates="ratings")
    creator = relationship("User", back_populates="ratings")
