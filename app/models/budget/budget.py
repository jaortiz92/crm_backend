"""
Budget Model

Master budget for projections of income and expenses.
Supports what-if scenarios via self-referential parent_budget_id.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class Budget(Base):
    """
    Master budget for projections of income and expenses.
    Supports what-if scenarios via self-referential parent_budget_id.
    """
    __tablename__ = "budgets"

    id_budget = Column(Integer, primary_key=True, index=True)
    budget_name = Column(String(120), nullable=False)
    budget_year = Column(Integer, nullable=False)
    budget_period = Column(String(20), nullable=False)
    id_department = Column(Integer, ForeignKey("departments.id_department"))
    status = Column(String(20), server_default="'draft'")
    is_scenario = Column(Boolean, server_default="False")
    parent_budget_id = Column(Integer, ForeignKey("budgets.id_budget"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    department = relationship("Department", backref="budgets")
    parent_budget = relationship("Budget", remote_side=[id_budget], backref="scenario_clones")

    budget_lines = relationship("BudgetLine", back_populates="budget")
