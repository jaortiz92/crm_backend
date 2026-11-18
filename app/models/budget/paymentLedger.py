"""
PaymentLedger Model

Single ledger of cash-flow movements and adjustments.
Ingested from Recibos.xlsx (SIIGO auxiliary ledger export).
Linked to invoices for payment imputation.
"""

from sqlalchemy import (
    Column, ForeignKey, Integer, String, Date, DateTime,
    Numeric, Text, CheckConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class PaymentLedger(Base):
    """
    Cash-flow and adjustment ledger.
    Ingested from Recibos.xlsx (SIIGO auxiliares).
    """
    __tablename__ = "payment_ledger"

    id_payment_ledger = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(60), nullable=False, index=True)
    transaction_nature = Column(
        String(25),
        CheckConstraint(
            "transaction_nature IN ('CASH','NON_CASH_ADJUSTMENT')",
            name="ck_payment_ledger_nature",
        ),
        nullable=False, server_default="CASH",
    )
    cash_flow = Column(
        String(8),
        CheckConstraint(
            "cash_flow IS NULL OR cash_flow IN ('in','out')",
            name="ck_payment_ledger_flow",
        ),
    )
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(15, 2), nullable=False, server_default="0")
    accounting_account = Column(String(20), nullable=False, server_default="")
    description = Column(Text)
    third_party = Column(String(200))
    id_account_receivable = Column(
        Integer, ForeignKey("accounts_receivable.id_account_receivable"), nullable=True
    )
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    payment_method = Column(String(40))
    reference_number = Column(String(60))
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    account_receivable = relationship("AccountReceivable", back_populates="payments")
    customer = relationship("Customer")
    invoice = relationship("Invoice", backref="payment_ledger")
