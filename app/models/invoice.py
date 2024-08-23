# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, Date
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base

class Invoice(Base):
    __tablename__ = "invoices"

    id_invoice = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(20), nullable=False)
    invoice_date = Column(Date, nullable=False)
    id_order = Column(Integer, ForeignKey("orders.id_order"))

    order = relationship("Order", back_populates="invoices")

    invoiceDetail = relationship("InvoiceDetail", back_populates="invoices")
    credit = relationship("Credit", back_populates="invoices")
    shipment = relationship("Shipment", back_populates="invoices")