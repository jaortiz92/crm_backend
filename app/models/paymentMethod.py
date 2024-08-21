# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String)
from sqlalchemy.orm import relationship

# APP
from db import Base

class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id_payment_method = Column(Integer, primary_key=True, index=True)
    payment_method = Column(String(100))
