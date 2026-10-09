"""
BudgetLine Model

Detail lines of a budget: projections per cost center.
Each line represents a projected income or expense for a given date.
"""

import enum

from sqlalchemy import (
    Boolean, Column, Date, Enum, ForeignKey, Float, Integer, Numeric, String,
    Text, Index, text,
)
from sqlalchemy.orm import relationship

from app.db import Base


class LineTypeEnum(str, enum.Enum):
    """BE-S8-BUDGET-PURCHASES (backend.02_18 §3.1): third member PURCHASE =
    imported-merchandise line (budget_date = import date, payment_date
    always NULL — supplier installments are read-derived from
    line_payable_terms, never materialized). The Postgres enum stores the
    NAMES ('INCOME'/'EXPENSE'/'PURCHASE'), so existing databases need the
    manual `ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS
    'PURCHASE';` BEFORE deploying (see §3.3 / note.md — create_all never
    alters an existing enum)."""
    INCOME = "income"
    EXPENSE = "expense"
    PURCHASE = "purchase"


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
    __table_args__ = (
        Index(
            "uq_budget_lines_financing_source",
            "id_budget", "source_engine", "source_engine_id", "cost_component_code",
            unique=True,
            postgresql_where=text("source_engine = 'financing_credit'"),
            sqlite_where=text("source_engine = 'financing_credit'"),
        ),
    )

    id_budget_line = Column(Integer, primary_key=True, index=True)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    line_type = Column(Enum(LineTypeEnum), nullable=False)
    budget_date = Column(Date, nullable=False)
    payment_date = Column(Date, nullable=True)
    id_collection = Column(Integer, ForeignKey("collections.id_collection"), nullable=True)
    projected_amount = Column(Numeric(15, 2), nullable=False, server_default="0")
    description = Column(Text)
    behavior_type = Column(Enum(BehaviorTypeEnum), nullable=False, server_default="fixed")
    variable_rate = Column(Float, nullable=True)
    # BE-S10-IVA (spec backend.02_20 §3.1): the ONLY materialized IVA datum.
    # NULL ≡ True is a RULE OF THE DERIVATION (D-S10-3: legacy files /
    # empty cells are "con IVA"), NOT a DB default — no backfill, no
    # server_default, so existing databases only need the manual ALTER of
    # §10 (BE-S6 include_carryover pattern; create_all never alters an
    # existing table). Meaningful for EXPENSE only: INCOME always taxed —
    # the flag persists but the derivation ignores it (D-S10-5) — and
    # PURCHASE always taxed on both streams (§3.1).
    has_iva = Column(Boolean, nullable=True)
    # BE-S11-COLLABORATORS (spec backend.02_21 §4.7, D-S11-5): the link
    # motor<->line. THREE nullable columns — NULL on every existing row,
    # so all current consumers are 100% backward compatible (NFR-05).
    # id_collaborator carries NO DB FK (spec §4.7: integrity is enforced
    # by the engine, not by the FK graph, so table-creation order never
    # matters). Existing databases need the manual ALTER of §4.8 phase 2
    # before deploying (create_all never alters an existing table — the
    # include_carryover / has_iva precedent, see note.md).
    # source_engine ∈ {collaborator_cost, collaborator_liquidation}; the
    # idempotent replacement (R-13) ONLY touches rows with
    # source_engine LIKE 'collaborator_%'.
    id_collaborator = Column(Integer, nullable=True)
    cost_component_code = Column(String(20), nullable=True)
    source_engine = Column(String(40), nullable=True)
    # BE-S12 financing: references the exact installment that owns an
    # interest/insurance expense; intentionally polymorphic (no FK).
    source_engine_id = Column(Integer, nullable=True)

    budget = relationship("Budget", back_populates="budget_lines")
    cost_center = relationship("CostCenter", back_populates="budget_lines")
    collection = relationship("Collection")
