from typing import Optional

from pydantic import BaseModel, Field


class LinePaymentRuleBase(BaseModel):
    id_line: int = Field(..., gt=0, description="FK to line")
    payment_pct: float = Field(..., ge=0, le=1, description="Payment percentage (0-1)")
    payment_days: int = Field(..., description="Days relative to budget_date. Negative = before, positive = after")


class LinePaymentRuleCreate(LinePaymentRuleBase):
    pass


class LinePaymentRule(LinePaymentRuleBase):
    id_line_payment_rule: int = Field(..., gt=0)

    class Config:
        from_attributes = True
