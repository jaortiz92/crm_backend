# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Float, Boolean, Date    
)
from sqlalchemy.orm import relationship

# APP
from db import Base

class Credit(Base):
    __tablename__ = "credits"

    id_credit = Column(Integer, primary_key=True, index=True)
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    term = Column(Integer, nullable=False)
    credit_value = Column(Float, nullable=False)
    payment_value = Column(Float, nullable=False)
    balance = Column(Float)
    paid = Column(Boolean, default=False)
    last_payment_date = Column(Date)

    invoice = relationship("Invoice", back_populates="credits")
