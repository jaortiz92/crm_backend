# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey, Float,
    Integer, String, Date
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id_invoice = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(20), unique=True,
                            index=True, nullable=False)
    invoice_date = Column(Date, nullable=False)
    id_order = Column(Integer, ForeignKey("orders.id_order"))
    total_quantity = Column(Float, default=0)
    total_without_tax = Column(Float, default=0)
    total_discount = Column(Float, default=0)
    total_with_tax = Column(Float, default=0)

    order = relationship("Order", back_populates="invoices")

    invoice_details = relationship("InvoiceDetail", back_populates="invoice")
    credits = relationship("Credit", back_populates="invoice")
    shipments = relationship("Shipment", back_populates="invoice")
