"""
LineInternmentTerm Model (BE-S9-INTERNMENT-SPLIT, backend.02_19 §3.2)

Internment payment terms per product line: master catalog, exact mirror
of ``line_payable_terms`` in shape/order/validations — but NOT
interchangeable with it.

SEMANTIC DIFFERENCE vs ``line_payable_terms`` (mandatory, spec §3.2): both
schedules share the same anchor (the purchase's ``budget_date`` = import
date, A-3) and the same D-7 installment order, but THE BASE DIFFERS:
``payment_pct`` here multiplies the COSTO DE INTERNACIÓN
(Total − Total/(1 + internment_pct), §4), while ``line_payable_terms``
multiplies the COSTO PROVEEDOR (Total / (1 + internment_pct)). A row of
this table is therefore NOT a supplier installment of the line's full
amount: pointing one Line's payable terms at the internment cost (or the
reverse) silently mis-places every installment.

Scales mirror the payable catalog: ``payment_pct`` is a fraction 0-1
(multiplicator) and ``payment_days`` an offset in days from the import
date (negative = before the anchor, same as BR-TERM-01; the typical
internment pattern is positive, e.g. 60 % at +15 d and 40 % at +45 d —
A-4, a UI default only, every Line admits N installments).

Flat catalog resolved by ``id_line`` (no new ORM relationships), exactly
like the payable-terms table (spec §3.3). Auto-created via
``Base.metadata.create_all`` — ZERO manual DDL (NFR-BE9-5, no Alembic).
"""

from sqlalchemy import Column, ForeignKey, Float, Integer

from app.db import Base


class LineInternmentTerm(Base):
    """Internment payment term (installment rule) of a product line."""
    __tablename__ = "line_internment_terms"

    id_line_internment_term = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False)
    payment_pct = Column(Float, nullable=False)
    payment_days = Column(Integer, nullable=False)
