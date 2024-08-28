# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class RatingCategory(Base):
    __tablename__ = "rating_categories"

    id_rating_category = Column(Integer, primary_key=True, index=True)
    rating_category = Column(String(20), nullable=False)
    level = Column(Integer, nullable=False)

    ratings = relationship("Rating", back_populates="rating_category")