"""
LineCostRate Model

Master catalog: budgeted COGS percentage per product line with validity
periods (Pilar 1 - P&L).  id_line = NULL defines the global fallback rate
used by cost centers whose line has no active rate.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Numeric, Date, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class LineCostRate(Base):
    """Budgeted COGS % per line, with validity period (D-2)."""
    __tablename__ = "line_cost_rates"

    id_line_cost_rate = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=True, index=True)
    rate_name = Column(String(120), nullable=True)
    cogs_pct = Column(Numeric(5, 2), nullable=False)
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    is_active = Column(Boolean, server_default="True")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    line = relationship("Line", backref="cost_rates")
