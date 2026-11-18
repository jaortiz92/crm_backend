"""
PayableLedger Model

Payment disbursement records for accounts payable.
Acts as the transaction log, allowing multiple payments per obligation.
"""

from sqlalchemy import Column, ForeignKey, Float, Integer, String, Date, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class PayableLedger(Base):
    """
    Payment disbursement records for accounts payable.
    Acts as the transaction log, allowing multiple payments per obligation.
    """
    __tablename__ = "payable_ledger"

    id_payable_ledger = Column(Integer, primary_key=True, index=True)
    id_account_payable = Column(
        Integer, ForeignKey("accounts_payable.id_account_payable"), nullable=False
    )
    payment_date = Column(Date, nullable=False)
    amount_paid = Column(Float, nullable=False)
    payment_reference = Column(String(60))
    created_at = Column(DateTime, server_default=func.now())

    account_payable = relationship("AccountPayable", back_populates="ledger_entries")
