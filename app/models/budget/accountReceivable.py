"""
AccountReceivable Model

Accounts receivable / portfolio status.
Ingested from EstadoCuenta306090.xlsx.
Linked to CRM customers for cross-referencing.
"""
import enum

from sqlalchemy import Column, Enum,ForeignKey, Float, Integer, String, Date, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base

class ReceivableStatusEnum(str, enum.Enum):
    OPEN = 'OPEN'
    PARTIAL = 'PARTIAL'
    PAID = 'PAID'


class AccountReceivable(Base):
    """
    Accounts receivable / portfolio status.
    Ingested from EstadoCuenta306090.xlsx.
    Linked to CRM customers for cross-referencing.
    """
    __tablename__ = "accounts_receivable"

    id_account_receivable = Column(Integer, primary_key=True, index=True)
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    document_number = Column(String(50), nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False, server_default="0")
    paid_amount = Column(Float, server_default="0")
    balance = Column(Float, server_default="0")
    status = Column(Enum(ReceivableStatusEnum), nullable=False, server_default=ReceivableStatusEnum.OPEN)
    aging_bucket = Column(String(20))
    source_file = Column(String(200))
    # --- Snapshot traceability (D-1) and statement cutoff (D-3) ---
    customer_document = Column(Float)                    # numeric root of Identificacion (JOIN-able)
    identification_original = Column(String(50))         # raw Excel text, e.g. "NIT 900576607 - 7"
    statement_date = Column(Date)                        # statement cutoff date
    created_at = Column(DateTime, server_default=func.now())

    customer = relationship("Customer", backref="accounts_receivable")
    invoice = relationship("Invoice", backref="accounts_receivable")

    payments = relationship("PaymentLedger", back_populates="account_receivable")
