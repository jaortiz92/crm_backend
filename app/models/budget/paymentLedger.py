"""
PaymentLedger Model

Payment collection records and behavior.
Ingested from RecibosDePago.xlsx.
Linked to invoices for payment tracking.
"""

from sqlalchemy import Column, ForeignKey, Float, Integer, String, Date, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class PaymentLedger(Base):
    """
    Payment collection records and behavior.
    Ingested from RecibosDePago.xlsx.
    Linked to invoices for payment tracking.
    """
    __tablename__ = "payment_ledger"

    id_payment_ledger = Column(Integer, primary_key=True, index=True)
    id_account_receivable = Column(
        Integer, ForeignKey("accounts_receivable.id_account_receivable"), nullable=False
    )
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Float, nullable=False, server_default="0")
    payment_method = Column(String(40))
    reference_number = Column(String(60))
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    account_receivable = relationship("AccountReceivable", back_populates="payments")
    invoice = relationship("Invoice", backref="payment_ledger")
