"""
Budget Model

Master budget for projections of income and expenses.
Supports what-if scenarios via self-referential parent_budget_id.
"""

from sqlalchemy import (
    Column, ForeignKey, Integer, String, DateTime, Boolean, Numeric, text,
)
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

    # BE-S6-CARRYOVER (spec backend.02_16 §3.1): per-scenario opt-in for the
    # prior-year balance carry-in on the planning cash flow. Pure preference
    # flag: BR-CO-01 guarantees ZERO server-side consumption outside the
    # /budget/planning/{id}/carryover endpoints, so no other endpoint's
    # behavior changes (NFR-S6-BE-2). Existing DBs need the manual ALTER of
    # §3.2 (no Alembic): ALTER TABLE budgets ADD COLUMN IF NOT EXISTS
    # include_carryover BOOLEAN NOT NULL DEFAULT FALSE;
    include_carryover = Column(Boolean, nullable=False, server_default=text("false"))

    # BE-S7-INITBAL (spec backend.02_25 §3.1): per-scenario configuration of
    # the two planning OPENING BALANCES (cash and warehouse), each with its
    # own mode 'carryover' | 'manual' (BR-IB-01 — only these two values,
    # anything else is a schema 422). The manual values are ALWAYS persisted
    # (even in carryover mode: they are the degradation base when there is
    # no source, BR-IB-04) and the server NEVER derives the carry-over value
    # (SA-1: the FE's cashFlowPivot owns that formula). Numeric type mirrors
    # budget_lines.projected_amount exactly (NUMERIC(15,2), repo convention).
    # Existing DBs need the manual ALTERs of §3.2 (no Alembic), documented in
    # note.md §5 — create_all never alters an existing table.
    initial_cash_mode = Column(String(20), nullable=False, server_default=text("'manual'"))
    initial_cash_manual = Column(Numeric(15, 2), nullable=False, server_default=text("'0'"))
    initial_warehouse_mode = Column(String(20), nullable=False, server_default=text("'manual'"))
    initial_warehouse_manual = Column(Numeric(15, 2), nullable=False, server_default=text("'0'"))

    department = relationship("Department", backref="budgets")
    parent_budget = relationship("Budget", remote_side=[id_budget], backref="scenario_clones")

    budget_lines = relationship("BudgetLine", back_populates="budget")
