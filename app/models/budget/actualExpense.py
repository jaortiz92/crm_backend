"""
ActualExpense Model

Records of real financial expenses (The Actuals).
Ingested from accounting system reports (e.g. LibroAuxiliarCECO.xlsx).
"""

from sqlalchemy import Column, ForeignKey, Float, Integer, String, Date, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class ActualExpense(Base):
    """
    Records of real financial expenses (The Actuals).
    Ingested from accounting system reports (e.g. LibroAuxiliarCECO.xlsx).
    """
    __tablename__ = "actual_expenses"

    id_actual_expense = Column(Integer, primary_key=True, index=True)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    expense_date = Column(Date, nullable=False)
    expense_type = Column(String(60), nullable=False)
    description = Column(Text)
    amount = Column(Float, nullable=False, server_default="0")
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    cost_center = relationship("CostCenter", back_populates="actual_expenses")
