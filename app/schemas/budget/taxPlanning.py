from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

class TaxProfileBase(BaseModel):
    profile_name: str = Field(..., max_length=120)
    tax_year: int = Field(..., ge=2000, le=2100)
    regime: str = Field(..., pattern="^(ordinary|simple)$")
    id_company: Optional[int] = None
    main_municipality_code: Optional[str] = None
    economic_activity_code: Optional[str] = None
    iva_responsible: bool = False
    withholding_agent: bool = False
    reteiva_agent: bool = False
    reteica_agent: bool = False
    status: str = Field("draft", pattern="^(draft|active|archived)$")
class TaxProfileCreate(TaxProfileBase): pass
class TaxProfile(TaxProfileBase):
    id_tax_profile: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config: from_attributes = True

class TaxRateBase(BaseModel):
    tax_type: str = Field(..., pattern="^(income_ordinary|simple|reteiva|withholding|ica|reteica)$")
    tax_year: int = Field(..., ge=2000, le=2100)
    regime: Optional[str] = Field(None, pattern="^(ordinary|simple)$")
    economic_activity_code: Optional[str] = None
    municipality_code: Optional[str] = None
    income_min: Optional[Decimal] = Field(None, ge=0)
    income_max: Optional[Decimal] = Field(None, ge=0)
    rate: Decimal = Field(..., ge=0, le=1)
    fixed_amount: Optional[Decimal] = Field(None, ge=0)
    base_type: str
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: bool = True
    source_note: Optional[str] = None
    @model_validator(mode="after")
    def valid_range(self):
        if self.income_min is not None and self.income_max is not None and self.income_max < self.income_min:
            raise ValueError("income_max must be greater than or equal to income_min")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be greater than or equal to valid_from")
        return self
class TaxRateCreate(TaxRateBase): pass
class TaxRate(TaxRateBase):
    id_tax_rate: int
    class Config: from_attributes = True

class TaxCalendarBase(BaseModel):
    tax_year: int = Field(..., ge=2000, le=2100)
    regime: Optional[str] = Field(None, pattern="^(ordinary|simple)$")
    tax_type: str
    period_code: str
    period_start: date
    period_end: date
    declaration_due_date: date
    payment_due_date: date
    payment_year: int = Field(..., ge=2000, le=2200)
    sequence: int = Field(..., ge=1)
    is_active: bool = True
    notes: Optional[str] = None
    @model_validator(mode="after")
    def valid_dates(self):
        if self.period_end < self.period_start: raise ValueError("period_end must be >= period_start")
        return self
class TaxCalendarCreate(TaxCalendarBase):
    @model_validator(mode="after")
    def valid_payment_year(self):
        # Write-time rule only: existing catalog rows may be stale and must stay
        # readable. The calculation treats payment_due_date as authoritative.
        if self.payment_year != self.payment_due_date.year:
            raise ValueError("payment_year must be the year of payment_due_date")
        return self
class TaxCalendar(TaxCalendarBase):
    id_tax_calendar_period: int
    class Config: from_attributes = True

class BudgetTaxAssumptionBase(BaseModel):
    id_tax_profile: int = Field(..., gt=0)
    taxable_income_adjustments: Decimal = Decimal("0")
    non_deductible_expenses: Decimal = Field(Decimal("0"), ge=0)
    exempt_income: Decimal = Field(Decimal("0"), ge=0)
    tax_losses: Decimal = Field(Decimal("0"), ge=0)
    tax_discounts: Decimal = Field(Decimal("0"), ge=0)
    prior_advances: Decimal = Field(Decimal("0"), ge=0)
    prior_withholdings: Decimal = Field(Decimal("0"), ge=0)
    monthly_sales_taxable_base: Optional[Dict[str, Decimal]] = None
    taxable_income_override: Optional[Decimal] = None
    withholding_base: Optional[Decimal] = Field(None, ge=0)
    withholding_suffered: Decimal = Field(Decimal("0"), ge=0)
    reteiva_suffered: Decimal = Field(Decimal("0"), ge=0)
    reteica_base: Optional[Decimal] = Field(None, ge=0)
    notes: Optional[str] = None
class BudgetTaxAssumptionCreate(BudgetTaxAssumptionBase): pass
class BudgetTaxAssumption(BudgetTaxAssumptionBase):
    id_budget_tax_assumption: int
    id_budget: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config: from_attributes = True

class BudgetTaxResult(BaseModel):
    id_budget_tax_result: int
    id_budget: int
    id_budget_tax_assumption: int
    tax_type: str
    period_start: date
    period_end: date
    taxable_base: Decimal
    tax_rate: Decimal
    tax_caused: Decimal
    advance_amount: Decimal
    withholding_amount: Decimal
    balance_payable: Decimal
    declaration_date: Optional[date] = None
    payment_date: Optional[date] = None
    payment_year: Optional[int] = None
    # P&L and cash are separate coordinates.  For credits (reteIVA,
    # withholding and reteICA) pnl_* is null by design: they remain visible
    # as saldos/credits and never become P&L expense.
    pnl_month: Optional[int] = Field(None, ge=1, le=12)
    pnl_year: Optional[int] = Field(None, ge=2000, le=2200)
    calculation_trace: Dict[str, Any] = {}
    warnings: List[str] = []
    calculated_at: Optional[datetime] = None
    class Config: from_attributes = True


class BudgetTaxTotals(BaseModel):
    """Aggregates returned alongside the period snapshots.

    These are additive response fields; the persisted result remains one row
    per tax obligation period, which is important for SIMPLE bimesters.
    """
    taxable_base: Decimal = Decimal("0")
    tax_caused: Decimal = Decimal("0")
    advance_amount: Decimal = Decimal("0")
    withholding_amount: Decimal = Decimal("0")
    balance_payable: Decimal = Decimal("0")


class BudgetTaxCalculationResponse(BaseModel):
    id_budget: int
    regime: str
    assumption: BudgetTaxAssumption
    warnings: List[str] = Field(default_factory=list)
    totals: BudgetTaxTotals = Field(default_factory=BudgetTaxTotals)
    results: List[BudgetTaxResult] = Field(default_factory=list)


class BudgetTaxCashFlowType(BaseModel):
    """One tax type inside a payment-month cash-flow bucket."""
    tax_type: str
    tax_caused: Decimal = Decimal("0")
    advance_amount: Decimal = Decimal("0")
    withholding_amount: Decimal = Decimal("0")
    payments: Decimal = Decimal("0")
    net_outflow: Decimal = Decimal("0")


class BudgetTaxCashFlowPeriod(BaseModel):
    """All tax snapshots payable in one payment month/year.

    ``payments`` is the post-credit balance payable.  ``net_outflow`` also
    includes advances because an advance is cash paid even when it reduces the
    later balance to zero.  Withholdings remain visible as credits and are not
    treated as a second expense/cash payment.
    """
    period: str
    payment_year: Optional[int] = None
    payment_month: Optional[int] = None
    tax_caused: Decimal = Decimal("0")
    advance_amount: Decimal = Decimal("0")
    withholding_amount: Decimal = Decimal("0")
    payments: Decimal = Decimal("0")
    net_outflow: Decimal = Decimal("0")
    # Readable aliases retained for API consumers that use plural labels.
    advances: Decimal = Decimal("0")
    withholdings: Decimal = Decimal("0")
    cash_outflow: Decimal = Decimal("0")
    by_type: List[BudgetTaxCashFlowType] = Field(default_factory=list)


class BudgetTaxCashFlowResponse(BaseModel):
    id_budget: int
    calculation_executed: bool = False
    monthly: List[BudgetTaxCashFlowPeriod] = Field(default_factory=list)
    totals: BudgetTaxCashFlowPeriod
    warnings: List[str] = Field(default_factory=list)
