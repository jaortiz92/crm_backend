"""
CostCenter Model

Master catalog of cost centers, aligned with the accounting system.
Linked to zones, areas and lines for operational dimension mapping.
"""

from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, Text
from sqlalchemy.orm import relationship

from app.db import Base


class CostCenter(Base):
    """
    Master catalog of cost centers, aligned with the accounting system.
    Linked to zones, areas and lines for operational dimension mapping.
    """
    __tablename__ = "cost_centers"

    id_cost_center = Column(Integer, primary_key=True, index=True)
    cost_center_code = Column(String(20), unique=True, index=True, nullable=False)
    cost_center_name = Column(String(120), nullable=False)
    id_zone = Column(Integer, ForeignKey("zones.id_zone"))
    id_area = Column(Integer, ForeignKey("areas.id_area"))
    id_line = Column(Integer, ForeignKey("lines.id_line"))
    is_active = Column(Boolean, server_default="True")
    description = Column(Text)

    zone = relationship("Zone", back_populates="cost_centers")
    area = relationship("Area", back_populates="cost_centers")
    line = relationship("Line", backref="cost_centers")

    actual_expenses = relationship("ActualExpense", back_populates="cost_center")
    actual_costs = relationship("ActualCost", back_populates="cost_center")
    budget_lines = relationship("BudgetLine", back_populates="cost_center")
