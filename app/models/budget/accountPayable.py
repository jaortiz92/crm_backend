"""
AccountPayable Model

Accounts payable / supplier obligations.
Represents the consolidated debt with Asian suppliers or logistics providers.
"""

import enum

from sqlalchemy import Column, Enum, ForeignKey, Float, Integer, String, Date, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class PayableStatusEnum(str, enum.Enum):
    OPEN = "open"
    PARTIAL = "partial"
    PAID = "paid"


class AccountPayable(Base):
    """
    Accounts payable / supplier obligations.
    Represents the consolidated debt with Asian suppliers or logistics providers.
    """
    __tablename__ = "accounts_payable"

    id_account_payable = Column(Integer, primary_key=True, index=True)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    supplier_name = Column(String(120), nullable=False)
    total_amount = Column(Float, nullable=False)
    balance = Column(Float, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(Enum(PayableStatusEnum), nullable=False, server_default="'open'")
    created_at = Column(DateTime, server_default=func.now())

    cost_center = relationship("CostCenter", backref="accounts_payable")
    ledger_entries = relationship("PayableLedger", back_populates="account_payable")
