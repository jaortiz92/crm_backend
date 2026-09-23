"""
IvaPeriod Model (BE-S10-IVA, backend.02_20 §3.2)

Settlement calendar of a fiscal year: one row per period covering the
stakeholder's bimestral pattern (e.g. ene-feb vence 2027-05-21) WITHOUT
hardcoding any DIAN rule (D-S10-10 — the calendar is configurable per
year, not a formula).

Flat catalog resolved by ``period_year`` (no new ORM relationships),
exactly like lineInternmentRate.py (spec §3.3 conventions). Auto-created
via ``Base.metadata.create_all`` — ZERO manual DDL (NFR-BE10-5, no
Alembic; the single manual ALTER of this feature is the budget_lines
.has_iva column, §3.1/§10).

Ranges between periods are deliberately NOT validated and never
overlap-checked at the data layer (spec §3.2): a settlement event takes
the FIRST period (``period_no`` ASC) whose [date_from, date_to] covers
its movement date, so gaps produce the ``unassigned`` bucket (§4.4) and
overlaps degrade deterministically. Hard uniqueness is only
(period_year, period_no) — the unique index below; the friendly 400 is
produced by the CRUD guard BEFORE the IntegrityError (mirrors the rate
catalog). No per-scenario validity: the calendar is PER YEAR and the
base + what-if scenarios of the same year SHARE it (single company,
ASM of §3.2).
"""

from sqlalchemy import Column, Date, Integer, String, UniqueConstraint

from app.db import Base


class IvaPeriod(Base):
    """Calendario de vencimientos de liquidación de IVA de un año fiscal."""
    __tablename__ = "iva_periods"

    id_iva_period = Column(Integer, primary_key=True, index=True)
    period_year = Column(Integer, nullable=False, index=True)   # año fiscal
    period_no = Column(Integer, nullable=False)                 # ordinal 1..N (bimestres: 1..6)
    date_from = Column(Date, nullable=False)                    # inicio del rango de caja
    date_to = Column(Date, nullable=False)                      # fin del rango (inclusive)
    payment_due_date = Column(Date, nullable=False)             # vencimiento de pago (p. ej. 2027-05-21)
    description = Column(String(120), nullable=True)

    __table_args__ = (UniqueConstraint("period_year", "period_no", name="uq_iva_periods_year_no"),)
