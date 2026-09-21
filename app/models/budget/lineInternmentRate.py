"""
LineInternmentRate Model (BE-S9-INTERNMENT-SPLIT, backend.02_19 §3.1)

Internment (customs/nationalization) cost rate of a product line: master
catalog with AT MOST one row per Line (``id_line`` UNIQUE — PQ-S9-4: a
single in-force value, no date validity; validity would be PQ-S9-3).

D-S9-1 SEMANTICS (the whole point of BE-S9): the projected_amount of a
purchase IS THE TOTAL COST (supplier invoice + internment). This rate is
the MARK-UP OVER THE SUPPLIER COST, expressed as a fraction 0-1:

    Total = CostoProveedor × (1 + pct)
    =>  CostoProveedor  = Total / (1 + pct)   -> paid via line_payable_terms
        CostoInternacion = Total − CostoProveedor -> paid via
                           line_internment_terms

SEMANTIC DIFFERENCE vs ``line_payable_terms``: this table is a RATE (the
split knob of §4), not an installment schedule — and even the related
``line_internment_terms`` table multiplies the INTERNMENT component, never
the full line amount (backend.02_19 §3.2). The absence of a row means
pct = 0 (A-5): the purchase degrades byte-identically to the pre-BE-S9
single supplier stream (NFR-BE9-3).

Flat catalog resolved by ``id_line`` (no new ORM relationships), exactly
like linePayableTerm.py (spec §3.3). Auto-created via
``Base.metadata.create_all`` — ZERO manual DDL (NFR-BE9-5, no Alembic).
"""

from sqlalchemy import Column, ForeignKey, Float, Integer

from app.db import Base


class LineInternmentRate(Base):
    """Internment-cost rate of a product line (mark-up on supplier cost)."""
    __tablename__ = "line_internment_rates"

    id_line_internment_rate = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False,
                     unique=True)
    internment_pct = Column(Float, nullable=False)
