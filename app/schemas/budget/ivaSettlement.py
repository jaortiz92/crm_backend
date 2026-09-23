"""
IVA Settlement Schemas (BE-S10-IVA, spec backend.02_20 §4.6/§5.2)

Transport shape of ``BudgetIvaEngine.settlement`` (GET
/budget/iva/settlement/{id_budget}). The engine answers plain dicts and
this contract mirrors §4.6 FIELD BY FIELD, including two LITERAL
conventions the acceptance criteria quote verbatim:

- ``totals.deductable`` keeps the stakeholder's spelling WITH the "t"
  (the per-period breakdown key IS ``deductible``) — both are wire
  contract, do not "fix" either one (§4.6).
- the deductible decomposition keys are EXACTLY the four §4.5 concepts
  (fixed_expenses E2, variable_expenses E3+E4, import_vat E5,
  nationalization_vat E6); the generated side has a single concept
  (ventas, E1) because every sale is taxed (D-S10-5).

Optionality follows §4.4: without a calendar ``periods`` is ``[]`` and
everything lands in ``unassigned`` (never an error), so only
``description`` and the year default are nullable — every numeric field
is always present, zero-filled (NFR-BE10-3: the FE pivots on stable
keys).
"""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IvaGeneratedBreakdown(BaseModel):
    """§4.5 generated side: single concept (ventas) — sales are ALWAYS
    taxed and the line flag is ignored (D-S10-5)."""

    ventas: float = 0.0


class IvaDeductibleBreakdown(BaseModel):
    """§4.5 deductible decomposition by source concept (E2..E6)."""

    fixed_expenses: float = 0.0
    variable_expenses: float = 0.0
    import_vat: float = 0.0
    nationalization_vat: float = 0.0


class IvaSettlementPeriod(BaseModel):
    """One calendar row with its §4.5 recurrence outcome. Raw floats are
    internal; every monetary field here is round(2) at the boundary
    (NFR-BE10-4)."""

    period_no: int
    date_from: date
    date_to: date
    payment_due_date: date
    description: Optional[str] = None
    generated: IvaGeneratedBreakdown = Field(default_factory=IvaGeneratedBreakdown)
    deductible: IvaDeductibleBreakdown = Field(default_factory=IvaDeductibleBreakdown)
    prior_balance: float = 0.0     # saldo a favor arrastrado (round(2))
    tax_base: float = 0.0          # generado - descontable - prior (<=0 => pago 0)
    payment: float = 0.0           # max(0, tax_base) — unico desembolso (A8)
    carry_balance: float = 0.0     # max(0, -tax_base) — arrastre ilimitado (§4.5)
    events_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class IvaUnassigned(BaseModel):
    """§4.4 bucket: in-year events covered by NO period (gaps) or all
    events when the year has no calendar. Reported apart and NEVER part
    of the recurrence."""

    generated: float = 0.0
    deductible: float = 0.0
    events_count: int = 0


class IvaSettlementTotals(BaseModel):
    """Column sums over PERIODS ONLY + the remaining favor balance.
    ``deductable`` is the §4.6 LITERAL (t included) — wire contract."""

    generated: float = 0.0
    deductable: float = 0.0
    payments: float = 0.0
    final_balance: float = 0.0


class IvaSettlementMeta(BaseModel):
    """warnings carries the §4.4 literal 'No IVA calendar for {year};
    configure /budget/iva-period' when the year has no calendar;
    out_of_year_events counts (and excludes) events whose movement date
    falls outside the settlement year (§4.4)."""

    warnings: List[str] = []
    out_of_year_events: int = 0
    filters: Dict[str, Any] = {}


class IvaSettlementResult(BaseModel):
    """Full §4.6 response contract of GET
    /budget/iva/settlement/{id_budget}."""

    id_budget: int
    budget_name: str
    year: int
    tax_rate_used: float
    basis: str = "cash"
    periods: List[IvaSettlementPeriod] = []
    unassigned: IvaUnassigned = Field(default_factory=IvaUnassigned)
    totals: IvaSettlementTotals = Field(default_factory=IvaSettlementTotals)
    meta: IvaSettlementMeta = Field(default_factory=IvaSettlementMeta)
