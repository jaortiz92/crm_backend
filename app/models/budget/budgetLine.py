"""
BudgetLine Model

Detail lines of a budget: monthly projections per cost center.
Each line represents a projected income or expense for a given month.
"""

import enum

from sqlalchemy import Column, Enum, ForeignKey, Float, Integer, Text
from sqlalchemy.orm import relationship

from app.db import Base


class LineTypeEnum(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class BudgetLine(Base):
    """
    Detail lines of a budget: monthly projections per cost center.
    Each line represents a projected income or expense for a given month.
    """
    __tablename__ = "budget_lines"

    id_budget_line = Column(Integer, primary_key=True, index=True)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    line_type = Column(Enum(LineTypeEnum), nullable=False)
    month = Column(Integer, nullable=False)
    projected_amount = Column(Float, nullable=False, server_default="0")
    description = Column(Text)

    budget = relationship("Budget", back_populates="budget_lines")
    cost_center = relationship("CostCenter", back_populates="budget_lines")
