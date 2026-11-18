"""Persistent configuration and snapshots for budget tax planning."""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.sql import func
from app.db import Base

MONEY = Numeric(18, 6)


class TaxProfile(Base):
    __tablename__ = "tax_profiles"
    id_tax_profile = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String(120), nullable=False)
    tax_year = Column(Integer, nullable=False, index=True)
    regime = Column(String(20), nullable=False)
    id_company = Column(Integer, nullable=True)
    main_municipality_code = Column(String(30), nullable=True)
    economic_activity_code = Column(String(30), nullable=True)
    iva_responsible = Column(Boolean, nullable=False, default=False)
    withholding_agent = Column(Boolean, nullable=False, default=False)
    reteiva_agent = Column(Boolean, nullable=False, default=False)
    reteica_agent = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (Index("uq_tax_profile_active_company_year_regime", "id_company", "tax_year", "regime",
                            unique=True, postgresql_where=text("status = 'active'")),)


class TaxRate(Base):
    __tablename__ = "tax_rates"
    id_tax_rate = Column(Integer, primary_key=True, index=True)
    tax_type = Column(String(30), nullable=False, index=True)
    tax_year = Column(Integer, nullable=False, index=True)
    regime = Column(String(20), nullable=True)
    economic_activity_code = Column(String(30), nullable=True)
    municipality_code = Column(String(30), nullable=True)
    income_min = Column(MONEY, nullable=True)
    income_max = Column(MONEY, nullable=True)
    rate = Column(MONEY, nullable=False)
    fixed_amount = Column(MONEY, nullable=True)
    base_type = Column(String(30), nullable=False)
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    source_note = Column(Text, nullable=True)


class TaxCalendarPeriod(Base):
    __tablename__ = "tax_calendar_periods"
    id_tax_calendar_period = Column(Integer, primary_key=True, index=True)
    tax_year = Column(Integer, nullable=False, index=True)
    regime = Column(String(20), nullable=True)
    tax_type = Column(String(30), nullable=False)
    period_code = Column(String(30), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    declaration_due_date = Column(Date, nullable=False)
    payment_due_date = Column(Date, nullable=False)
    payment_year = Column(Integer, nullable=False)
    sequence = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=True)


class BudgetTaxAssumption(Base):
    __tablename__ = "budget_tax_assumptions"
    id_budget_tax_assumption = Column(Integer, primary_key=True, index=True)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False, index=True)
    id_tax_profile = Column(Integer, ForeignKey("tax_profiles.id_tax_profile"), nullable=False)
    taxable_income_adjustments = Column(MONEY, nullable=False, default=0)
    non_deductible_expenses = Column(MONEY, nullable=False, default=0)
    exempt_income = Column(MONEY, nullable=False, default=0)
    tax_losses = Column(MONEY, nullable=False, default=0)
    tax_discounts = Column(MONEY, nullable=False, default=0)
    prior_advances = Column(MONEY, nullable=False, default=0)
    prior_withholdings = Column(MONEY, nullable=False, default=0)
    monthly_sales_taxable_base = Column(JSON, nullable=True)
    taxable_income_override = Column(MONEY, nullable=True)
    withholding_base = Column(MONEY, nullable=True)
    withholding_suffered = Column(MONEY, nullable=False, default=0)
    reteiva_suffered = Column(MONEY, nullable=False, default=0)
    reteica_base = Column(MONEY, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("id_budget", "id_tax_profile", name="uq_budget_tax_assumption"),)


class BudgetTaxResult(Base):
    __tablename__ = "budget_tax_results"
    id_budget_tax_result = Column(Integer, primary_key=True, index=True)
    id_budget = Column(Integer, ForeignKey("budgets.id_budget"), nullable=False, index=True)
    id_budget_tax_assumption = Column(Integer, ForeignKey("budget_tax_assumptions.id_budget_tax_assumption"), nullable=False)
    tax_type = Column(String(30), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    taxable_base = Column(MONEY, nullable=False)
    tax_rate = Column(MONEY, nullable=False)
    tax_caused = Column(MONEY, nullable=False)
    advance_amount = Column(MONEY, nullable=False, default=0)
    withholding_amount = Column(MONEY, nullable=False, default=0)
    balance_payable = Column(MONEY, nullable=False, default=0)
    declaration_date = Column(Date, nullable=True)
    payment_date = Column(Date, nullable=True)
    payment_year = Column(Integer, nullable=True)
    calculation_trace = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    calculated_at = Column(DateTime, server_default=func.now())

    @property
    def pnl_month(self):
        """API-only coordinate stored in the calculation snapshot trace."""
        return (self.calculation_trace or {}).get("pnl_month")

    @property
    def pnl_year(self):
        """API-only coordinate stored in the calculation snapshot trace."""
        return (self.calculation_trace or {}).get("pnl_year")
