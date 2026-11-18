"""
IvaPeriod Schemas (BE-S10-IVA, spec backend.02_20 §5.2)

Contract for the settlement-calendar catalog endpoints. Triple
Base/Create/IvaPeriod mirroring lineInternmentRate.py
(``from_attributes=True`` on the shared base; the response class only
adds the surrogate id). Validations:

- ``period_year`` ∈ [2000, 2100] and ``period_no`` ∈ [1, 36] via Field
  bounds -> 422 outside the range (AC-BE10-5: the 36 cap covers any
  monthly/finer yearly split while keeping the catalog sane).
- ``date_to >= date_from`` via a model_validator -> 422 (AC-BE10-5).
  Overlapping ranges are NOT validated here on purpose (spec §3.2): the
  first-cover rule of §4.4 degrades them deterministically.
- Uniqueness of (period_year, period_no) is answered as the friendly 400
  by the API layer BEFORE the unique index could raise (mirror of the
  internment-rate guard).

Dates are plain ISO (fastapi/pydantic default serialization).
"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IvaPeriodBase(BaseModel):
    period_year: int = Field(..., ge=2000, le=2100,
                             description="Fiscal year the calendar belongs to")
    period_no: int = Field(..., ge=1, le=36,
                           description="Ordinal inside the year (bimestres: 1..6)")
    date_from: date = Field(..., description="First cash date covered (inclusive)")
    date_to: date = Field(..., description="Last cash date covered (inclusive)")
    payment_due_date: date = Field(
        ..., description="Settlement payment due date (e.g. 2027-05-21)",
    )
    description: Optional[str] = Field(None, max_length=120)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def check_date_range(self) -> "IvaPeriodBase":
        # AC-BE10-5: an inverted range is a 422 (date_to >= date_from).
        if self.date_to < self.date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        return self


class IvaPeriodCreate(IvaPeriodBase):
    pass


class IvaPeriod(IvaPeriodBase):
    id_iva_period: int = Field(..., gt=0)
