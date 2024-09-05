# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String,
    Date, Float, Text    
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Shipment(Base):
    __tablename__ = "shipments"

    id_shipment = Column(Integer, primary_key=True, index=True)
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    shipment_date = Column(Date, nullable=False)
    carrier = Column(String(50), nullable=False)
    tracking_number = Column(String(100), nullable=False)
    received_date = Column(Date, nullable=False)
    shipment_cost = Column(Float, nullable=False)
    details = Column(Text)

    invoice = relationship("Invoice", back_populates="shipments")
