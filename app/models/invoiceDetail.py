# SQLalchemy
from sqlalchemy import (
    Column, ForeignKey,
    Integer, String, 
    Float, Enum
)
from sqlalchemy.orm import relationship

# APP
from app.db import Base
from app.core import Gender

class InvoiceDetail(Base):
    __tablename__ = "invoice_details"

    id_invoice_detail = Column(Integer, primary_key=True, index=True)
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    product = Column(String(50), nullable=False)
    color = Column(String(50), nullable=False)
    size = Column(String(50), nullable=False)
    id_brand = Column(Integer, ForeignKey("brands.id_brand"))
    gender = Column(Enum(Gender), nullable=False)  # 'M', 'F', 'U'
    unit_value = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    value_without_vat = Column(Float, nullable=False)
    discount = Column(Float, nullable=False)
    value_with_vat = Column(Float, nullable=False)

    invoice = relationship("Invoice", back_populates="invoice_details")
    brand = relationship("Brand", back_populates="invoice_details")
