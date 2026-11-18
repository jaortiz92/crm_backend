"""
BudgetScenario Model

What-if scenario sandbox for simulations.
Stores scenario parameters and results without affecting production data.
Supports cloning budgets for dynamic simulation (e.g. freight increases,
payment term changes).
"""

from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class BudgetScenario(Base):
    """
    What-if scenario sandbox for simulations.
    Stores scenario parameters and results without affecting production data.
    Supports cloning budgets for dynamic simulation (e.g. freight increases,
    payment term changes).
    """
    __tablename__ = "budget_scenarios"

    id_budget_scenario = Column(Integer, primary_key=True, index=True)
    scenario_name = Column(String(120), nullable=False)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False)
    scenario_type = Column(String(40), nullable=False)
    parameters = Column(JSON)
    results = Column(JSON)
    is_active = Column(Boolean, server_default="True")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    budget = relationship("Budget", backref="scenarios")
