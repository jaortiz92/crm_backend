"""
LinePayableTerm Schemas (BE-S5-PAYABLE-TERMS)

Contract for the supplier-payment-terms catalog endpoints
(spec backend.02_15 §3.1 / §5). ``payment_pct`` is stored as a FRACTION
0-1 (same semantics as the collections ``line_payment_rules.payment_pct``:
the amount is MULTIPLIED by it — D-6); the UI handles percents client-side
(mirror of FE-S5 FD-8). Validation ``gt=0, le=1`` -> 422 outside the range
(AC-S5-BE-8); zero-pct rows would silently drop installments, hence the
exclusive lower bound.
"""

from pydantic import BaseModel, Field, ConfigDict


class LinePayableTermBase(BaseModel):
    id_line: int = Field(..., gt=0, description="FK to line (lines.id_line)")
    payment_pct: float = Field(
        ..., gt=0, le=1,
        description="Installment fraction (0-1, exclusive of 0): the "
                    "projected amount is multiplied by it (D-6)",
    )
    payment_days: int = Field(
        ...,
        description="Offset in days from budget_date (anchor = import "
                    "date). Negative = before, 0 = the day, positive = "
                    "after (BR-TERM-01)",
    )

    model_config = ConfigDict(from_attributes=True)


class LinePayableTermCreate(LinePayableTermBase):
    pass


class LinePayableTerm(LinePayableTermBase):
    id_line_payable_term: int = Field(..., gt=0)
