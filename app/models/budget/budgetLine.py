"""
BudgetLine Model

Detail lines of a budget: projections per cost center.
Each line represents a projected income or expense for a given date.
"""

import enum

from sqlalchemy import Column, Date, Enum, ForeignKey, Float, Integer, Text
from sqlalchemy.orm import relationship

from app.db import Base


class LineTypeEnum(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class BehaviorTypeEnum(str, enum.Enum):
    FIXED = "fixed"
    VARIABLE_SALES = "variable_sales"
    VARIABLE_RECEIVABLES = "variable_receivables"


class BudgetLine(Base):
    """
    Detail lines of a budget: projections per cost center.
    Each line represents a projected income or expense for a given date.
    """
    __tablename__ = "budget_lines"

    id_budget_line = Column(Integer, primary_key=True, index=True)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    line_type = Column(Enum(LineTypeEnum), nullable=False)
    budget_date = Column(Date, nullable=False)
    payment_date = Column(Date, nullable=True)
    id_collection = Column(Integer, ForeignKey("collections.id_collection"), nullable=True)
    projected_amount = Column(Float, nullable=False, server_default="0")
    description = Column(Text)
    behavior_type = Column(Enum(BehaviorTypeEnum), nullable=False, server_default="fixed")
    variable_rate = Column(Float, nullable=True)

    budget = relationship("Budget", back_populates="budget_lines")
    cost_center = relationship("CostCenter", back_populates="budget_lines")
    collection = relationship("Collection")
