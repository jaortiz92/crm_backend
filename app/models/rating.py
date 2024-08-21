# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Text, Date    
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Rating(Base):
    __tablename__ = "ratings"

    id_rating = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_rating_category = Column(Integer, ForeignKey("rating_categories.id_rating_category"))
    date = Column(Date, nullable=False)
    comments = Column(Text)

    customer = relationship("customer", back_populates="ratings")
    rating_category = relationship("RatingCategory", back_populates="ratings")
