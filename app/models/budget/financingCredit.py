"""Company financing debt and its versioned projected installments."""

from sqlalchemy import (
    CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class FinancingCredit(Base):
    __tablename__ = "financing_credits"
    __table_args__ = (
        CheckConstraint("opening_balance > 0", name="ck_financing_credit_opening_balance"),
        CheckConstraint("annual_rate >= 0", name="ck_financing_credit_annual_rate"),
        CheckConstraint("term_installments > 0", name="ck_financing_credit_term"),
        CheckConstraint(
            "insurance_per_installment >= 0",
            name="ck_financing_credit_insurance_nonnegative",
        ),
        CheckConstraint(
            "original_principal IS NULL OR original_principal > 0",
            name="ck_financing_credit_original_principal",
        ),
        CheckConstraint("status IN ('active', 'closed')", name="ck_financing_credit_status"),
        CheckConstraint("origin_type IN ('new', 'legacy')", name="ck_financing_credit_origin"),
        CheckConstraint(
            "method IN ('french_fixed_payment', 'german_fixed_principal')",
            name="ck_financing_credit_method",
        ),
        CheckConstraint("currency = 'COP'", name="ck_financing_credit_currency"),
        CheckConstraint("frequency = 'monthly'", name="ck_financing_credit_frequency"),
        CheckConstraint(
            "(status = 'active' AND closure_date IS NULL AND closure_balance IS NULL) "
            "OR (status = 'closed' AND closure_date IS NOT NULL AND closure_balance = 0)",
            name="ck_financing_credit_closure_state",
        ),
        CheckConstraint(
            "rate_convention IN ('nominal_annual', 'effective_annual')",
            name="ck_financing_credit_rate_convention",
        ),
        CheckConstraint(
            "day_count_convention = 'monthly_periodic'",
            name="ck_financing_credit_day_count",
        ),
        CheckConstraint(
            "(origin_type = 'legacy' AND cutoff_date IS NOT NULL "
            "AND disbursement_date IS NULL AND original_principal IS NULL "
            "AND first_due_date > cutoff_date) "
            "OR (origin_type = 'new' AND disbursement_date IS NOT NULL "
            "AND original_principal IS NOT NULL AND opening_balance = original_principal "
            "AND first_due_date > disbursement_date)",
            name="ck_financing_credit_origin_dates",
        ),
        Index("ix_financing_credits_cost_center", "id_cost_center"),
        Index("ix_financing_credits_status", "status"),
        Index("ix_financing_credits_cutoff", "cutoff_date"),
        Index("ix_financing_credits_origin", "origin_type"),
    )

    id_financing_credit = Column(Integer, primary_key=True, index=True)
    name = Column(String(160), nullable=False)
    lender_name = Column(String(160), nullable=False)
    credit_type = Column(String(80), nullable=True)
    status = Column(String(16), nullable=False, server_default="active")
    origin_type = Column(String(16), nullable=False)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    method = Column(String(32), nullable=False)
    currency = Column(String(3), nullable=False, server_default="COP")
    disbursement_date = Column(Date, nullable=True)
    original_principal = Column(Numeric(15, 2), nullable=True)
    cutoff_date = Column(Date, nullable=True)
    opening_balance = Column(Numeric(15, 2), nullable=False)
    annual_rate = Column(Numeric(9, 6), nullable=False)
    rate_convention = Column(String(24), nullable=False)
    day_count_convention = Column(String(32), nullable=False)
    frequency = Column(String(16), nullable=False)
    term_installments = Column(Integer, nullable=False)
    first_due_date = Column(Date, nullable=False)
    insurance_per_installment = Column(Numeric(15, 2), nullable=False)
    schedule_revision = Column(Integer, nullable=False, server_default="1")
    closure_date = Column(Date, nullable=True)
    closure_balance = Column(Numeric(15, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    cost_center = relationship("CostCenter")
    installments = relationship(
        "FinancingCreditInstallment", back_populates="financing_credit",
        cascade="all, delete-orphan",
    )


class FinancingCreditInstallment(Base):
    __tablename__ = "financing_credit_installments"
    __table_args__ = (
        UniqueConstraint(
            "id_financing_credit", "installment_number", "schedule_revision",
            name="uq_financing_installment_revision",
        ),
        CheckConstraint("installment_number > 0", name="ck_financing_installment_number"),
        CheckConstraint("principal_amount >= 0", name="ck_financing_principal_nonnegative"),
        CheckConstraint("interest_amount >= 0", name="ck_financing_interest_nonnegative"),
        CheckConstraint("insurance_amount >= 0", name="ck_financing_insurance_nonnegative"),
        CheckConstraint("opening_balance > 0", name="ck_financing_installment_opening_positive"),
        CheckConstraint("closing_balance >= 0", name="ck_financing_closing_nonnegative"),
        CheckConstraint("rate_used >= 0", name="ck_financing_installment_rate_nonnegative"),
        CheckConstraint("id_cost_center > 0", name="ck_financing_installment_cost_center"),
        CheckConstraint(
            "rate_convention IN ('nominal_annual', 'effective_annual')",
            name="ck_financing_installment_rate_convention",
        ),
        CheckConstraint(
            "day_count_convention = 'monthly_periodic'",
            name="ck_financing_installment_day_count",
        ),
        CheckConstraint(
            "method IN ('french_fixed_payment', 'german_fixed_principal')",
            name="ck_financing_installment_method",
        ),
        CheckConstraint(
            "projection_status IN ('projected', 'suspended')",
            name="ck_financing_installment_projection_status",
        ),
        Index("ix_financing_installments_principal_date", "principal_due_date"),
    )

    id_financing_credit_installment = Column(Integer, primary_key=True, index=True)
    id_financing_credit = Column(
        Integer, ForeignKey("financing_credits.id_financing_credit", ondelete="CASCADE"),
        nullable=False,
    )
    installment_number = Column(Integer, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    principal_amount = Column(Numeric(15, 2), nullable=False)
    principal_due_date = Column(Date, nullable=False)
    interest_amount = Column(Numeric(15, 2), nullable=False)
    interest_due_date = Column(Date, nullable=False)
    insurance_amount = Column(Numeric(15, 2), nullable=False)
    insurance_due_date = Column(Date, nullable=False)
    opening_balance = Column(Numeric(15, 2), nullable=False)
    closing_balance = Column(Numeric(15, 2), nullable=False)
    rate_used = Column(Numeric(9, 6), nullable=False)
    rate_convention = Column(String(24), nullable=False)
    day_count_convention = Column(String(32), nullable=False)
    method = Column(String(32), nullable=False)
    id_cost_center = Column(Integer, nullable=False)
    schedule_revision = Column(Integer, nullable=False)
    projection_status = Column(String(16), nullable=False, server_default="projected")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    financing_credit = relationship("FinancingCredit", back_populates="installments")

    @property
    def total_amount(self):
        return self.principal_amount + self.interest_amount + self.insurance_amount
