"""API contracts for company financing credits and projected installments."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional, List

from pydantic import BaseModel, ConfigDict, Field, model_validator


Method = Literal["french_fixed_payment", "german_fixed_principal"]
DayCountConvention = Literal["monthly_periodic"]


class FinancingCreditCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    lender_name: str = Field(..., min_length=1, max_length=160)
    credit_type: Optional[str] = Field(None, max_length=80)
    origin_type: Literal["new", "legacy"]
    id_cost_center: int = Field(..., gt=0)
    method: Method
    currency: Literal["COP"] = "COP"
    disbursement_date: Optional[date] = None
    original_principal: Optional[Decimal] = Field(None, gt=0, max_digits=15, decimal_places=2)
    cutoff_date: Optional[date] = None
    opening_balance: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    annual_rate: Decimal = Field(..., ge=0, max_digits=9, decimal_places=6)
    # Required: no hidden default for the unsettled financial convention.
    rate_convention: str = Field(
        ..., description="Required explicitly: nominal_annual or effective_annual"
    )
    day_count_convention: DayCountConvention = "monthly_periodic"
    frequency: Literal["monthly"] = "monthly"
    term_installments: int = Field(..., gt=0, le=360)
    first_due_date: Optional[date] = None
    insurance_per_installment: Decimal = Field(..., ge=0, max_digits=15, decimal_places=2)

    @model_validator(mode="after")
    def validate_origin_fields(self):
        if self.origin_type == "new":
            if self.disbursement_date is None or self.original_principal is None:
                raise ValueError("new financing credits require disbursement_date and original_principal")
            if self.opening_balance != self.original_principal:
                raise ValueError("opening_balance must equal original_principal for new credits")
            if self.first_due_date is not None and self.first_due_date <= self.disbursement_date:
                raise ValueError("first_due_date must be after disbursement_date")
            if self.cutoff_date is not None:
                raise ValueError("cutoff_date is only valid for legacy credits")
        else:
            if self.cutoff_date is None:
                raise ValueError("legacy financing credits require cutoff_date")
            if self.first_due_date is None:
                raise ValueError("legacy financing credits require first_due_date")
            if self.first_due_date <= self.cutoff_date:
                raise ValueError("first_due_date must be after cutoff_date")
            if self.disbursement_date is not None or self.original_principal is not None:
                raise ValueError("disbursement_date and original_principal are not used for legacy credits")
        return self


class FinancingCreditUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    lender_name: Optional[str] = Field(None, min_length=1, max_length=160)
    credit_type: Optional[str] = Field(None, max_length=80)
    id_cost_center: Optional[int] = Field(None, gt=0)
    method: Optional[Method] = None
    disbursement_date: Optional[date] = None
    original_principal: Optional[Decimal] = Field(None, gt=0, max_digits=15, decimal_places=2)
    cutoff_date: Optional[date] = None
    opening_balance: Optional[Decimal] = Field(None, gt=0, max_digits=15, decimal_places=2)
    annual_rate: Optional[Decimal] = Field(None, ge=0, max_digits=9, decimal_places=6)
    rate_convention: Optional[str] = None
    day_count_convention: Optional[DayCountConvention] = None
    frequency: Optional[Literal["monthly"]] = None
    term_installments: Optional[int] = Field(None, gt=0, le=360)
    first_due_date: Optional[date] = None
    insurance_per_installment: Optional[Decimal] = Field(None, ge=0, max_digits=15, decimal_places=2)


class FinancingInstallmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_financing_credit_installment: Optional[int] = None
    id_financing_credit: Optional[int] = None
    installment_number: int
    period_start: date
    period_end: date
    principal_amount: Decimal
    principal_due_date: date
    interest_amount: Decimal
    interest_due_date: date
    insurance_amount: Decimal
    insurance_due_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    rate_used: Decimal
    rate_convention: str
    day_count_convention: str
    method: Method
    id_cost_center: int
    schedule_revision: Optional[int] = None
    projection_status: Literal["projected", "suspended"] = "projected"
    total_amount: Decimal


class FinancingScheduleTotals(BaseModel):
    principal: Decimal
    interest: Decimal
    insurance: Decimal
    total_cash_outflow: Decimal


class FinancingSchedulePreview(BaseModel):
    conditions: FinancingCreditCreate
    schedule: List[FinancingInstallmentOut]
    totals: FinancingScheduleTotals
    warnings: List[str] = []


class FinancingCreditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_financing_credit: int
    name: str
    lender_name: str
    credit_type: Optional[str] = None
    status: Literal["active", "closed"]
    origin_type: Literal["new", "legacy"]
    id_cost_center: int
    method: Method
    currency: str
    disbursement_date: Optional[date] = None
    original_principal: Optional[Decimal] = None
    cutoff_date: Optional[date] = None
    opening_balance: Decimal
    annual_rate: Decimal
    rate_convention: str
    day_count_convention: str
    frequency: str
    term_installments: int
    first_due_date: date
    insurance_per_installment: Decimal
    schedule_revision: int
    closure_date: Optional[date] = None
    closure_balance: Optional[Decimal] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    totals: FinancingScheduleTotals
    warnings: List[str] = []


class FinancingCreditDetail(FinancingCreditOut):
    installments: List[FinancingInstallmentOut]


class FinancingCreditListResponse(BaseModel):
    total: int
    items: List[FinancingCreditOut]


class FinancingRecalculateResult(BaseModel):
    id_financing_credit: int
    schedule_revision: int
    replaced_installments: int
    created_installments: int
    replaced_budget_lines: int
    created_budget_lines: int
    warnings: List[str] = []


class FinancingCloseRequest(BaseModel):
    cutoff_date: date
    remaining_balance: Decimal = Field(..., ge=0, max_digits=15, decimal_places=2)


class FinancingCloseResult(BaseModel):
    id_financing_credit: int
    status: Literal["closed"]
    suspended_installments: int
    message: str


class FinancingCreditDeleteResult(BaseModel):
    id_financing_credit: int
    budget_lines: int
    installments: int
