"""
LinePayableTerm Model (BE-S5-PAYABLE-TERMS; re-semantized by
BE-S7-COGS-PAYFLOW, backend.02_17 §2 / D-S7-1)

Supplier payment terms per product line: master catalog.

BE-S7 NOTE (new meaning, table/CRUD code untouched): these terms NO
LONGER materialize expense budget_lines into installments (the BE-S5
expansion was rolled back). They now describe how WE PAY THE SUPPLIER
the COST OF SALES (COGS) of a Line — consumed only by (a) the derived
carryover rows of GET /budget/planning/{id}/carryover (backend.02_17 §4,
crud.get_carryover_cogs_lines) and (b) the FE-S7 live "Pago a
proveedores (costo)" derivation. Scales unchanged: ``payment_pct`` is a
fraction 0-1 (multiplicator) and ``payment_days`` an offset from the
anchor (negative = before the anchor, BR-TERM-01 still names this rule).

MIRROR concept of ``line_payment_rules`` — but that legacy table describes
how CLIENTS pay us (collections; still materialized, BR-ING-05 intact) and
MUST NOT be reused for what we pay suppliers (D-1, stakeholder decision).
Each row is one supplier-payment installment rule of a Line.

Flat catalog resolved by ``id_line`` (no new ORM relationships), exactly
like the legacy rules table (spec §3). Auto-created via
``Base.metadata.create_all`` (NFR-S5-BE-1, no Alembic).
"""

from sqlalchemy import Column, ForeignKey, Float, Integer

from app.db import Base


class LinePayableTerm(Base):
    """Supplier payment term (installment rule) of a product line."""
    __tablename__ = "line_payable_terms"

    id_line_payable_term = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False)
    payment_pct = Column(Float, nullable=False)
    payment_days = Column(Integer, nullable=False)
