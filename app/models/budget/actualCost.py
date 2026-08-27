"""
ActualCost Model

Records of real financial costs (The Actuals).
Ingested from accounting system reports (e.g. CostosFinal.xlsx).
"""

from sqlalchemy import Column, ForeignKey, Float, Integer, String, Numeric, Date, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class ActualCost(Base):
    """
    Records of real financial costs (The Actuals).
    Ingested from accounting system reports (e.g. CostosFinal.xlsx).
    """
    __tablename__ = "actual_costs"

    id_actual_cost = Column(Integer, primary_key=True, index=True)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    id_reference = Column(Integer, ForeignKey("product_references.id_reference"), nullable=True)
    document_number = Column(String(50), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, server_default="0")
    unit_cost = Column(Numeric(12, 2), nullable=False, server_default="0")
    cost_date = Column(Date, nullable=False)
    cost_type = Column(String(60), nullable=False)
    amount = Column(Float, nullable=False, server_default="0")
    description = Column(Text, nullable=True)
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    cost_center = relationship("CostCenter", back_populates="actual_costs")
    reference = relationship("Reference", back_populates="actual_costs")


