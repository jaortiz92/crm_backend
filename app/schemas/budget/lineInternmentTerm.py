"""
LineInternmentTerm Schemas (BE-S9-INTERNMENT-SPLIT)

Contract for the internment-payment-terms catalog endpoints
(spec backend.02_19 §3.2 / §5.3), an EXACT mirror of
linePayableTerm.py in shape and validations — the ONLY difference is the
BASE the percentages multiply: ``payment_pct`` here scales the COSTO DE
INTERNACIÓN (Total − Total/(1 + internment_pct), §4), never the full
purchase amount, so the two catalogs are NOT interchangeable. Stored as a
FRACTION 0-1 (the amount is MULTIPLIED by it — D-6 mirror); the UI handles
percents client-side (mirror of FE-S5 FD-8, A-4: 60 %/+15 d and 40 %/+45 d
is only a creation default). Validation ``gt=0, le=1`` -> 422 outside the
range (zero-pct rows would silently drop installments, hence the exclusive
lower bound — AC-BE9-2).
"""

from pydantic import BaseModel, Field, ConfigDict


class LineInternmentTermBase(BaseModel):
    id_line: int = Field(..., gt=0, description="FK to line (lines.id_line)")
    payment_pct: float = Field(
        ..., gt=0, le=1,
        description="Installment fraction (0-1, exclusive of 0): the "
                    "INTERNMENT cost (not the line's full amount) is "
                    "multiplied by it (§4)",
    )
    payment_days: int = Field(
        ...,
        description="Offset in days from budget_date (anchor = import "
                    "date, A-3 — same anchor as the supplier stream). "
                    "Negative = before, 0 = the day, positive = after "
                    "(BR-TERM-01 mirror; the typical pattern is positive)",
    )

    model_config = ConfigDict(from_attributes=True)


class LineInternmentTermCreate(LineInternmentTermBase):
    pass


class LineInternmentTerm(LineInternmentTermBase):
    id_line_internment_term: int = Field(..., gt=0)
