"""
Planning Schemas (BE-S4-BUDGET-PLANNING)

Request/response models for the /budget/planning sub-router
(spec backend.02_12 §5). BE-S4 itself mapped to the existing budgets /
budget_lines model surface only; BE-S6-CARRYOVER (backend.02_16) appends
the carryover contracts at the bottom (PlanningCarryover* schemas) and
mirrors the new budgets.include_carryover column on PlanningScenarioRow.

BE-S7-COGS-PAYFLOW (backend.02_17 §2) ROLLED BACK the BE-S5 expense
installment expansion: ``PlanningLineCreateResult`` (with
``expanded_siblings``) no longer exists and POST
/budget/planning/{id_budget}/line answers a plain ``BudgetLine`` again.
§4 of the same spec extends ``PlanningCarryoverLine`` with ``origin``
("line" material | "cogs" derived COGS installment) and makes
``id_budget_line`` nullable (derived rows are never persisted).
BE-S8-BUDGET-PURCHASES (backend.02_18 §5.2) widens ``origin`` with
"purchase" (derived supplier installment of a purchase row of the
source), adds the default-valued ``lines_purchase`` / ``total_purchase``
keys to ``PlanningUploadResult`` (optional third upload file) and lets
``PlanningLineCreate.line_type`` accept "purchase" (guards in the CRUD).
"""

import math
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .budget import BudgetFull
from .budgetLine import BehaviorTypeEnum, LineTypeEnum


class PlanningUploadResult(BaseModel):
    """Response 201 for POST /budget/planning/upload (spec §5.1).

    BE-S8-BUDGET-PURCHASES §5.2: additive defaults-only keys for the
    optional third file — ``lines_purchase`` / ``total_purchase`` stay at
    0 when no ``file_compras`` was sent, so the payload shape remains
    compatible for old clients (they simply ignore the new keys)."""

    id_budget: int
    scenario_name: str
    budget_year: int
    lines_income: int
    lines_expense: int
    # Sum of projected_amount over income budget_lines created.
    total_income: float
    # Sum of projected_amount over expense budget_lines created; variable
    # rows contribute 0 (their amount lives in variable_rate).
    total_expense_fixed: float
    # Extra lines produced by line_payment_rules expansion:
    # lines_income - processed_excel_income_rows (BR-ING-05).
    payment_rules_expansions: int
    # BE-S8 §5.2: one Excel purchase row == one budget_line (no
    # installment expansion, ever); count over the created PURCHASE rows.
    lines_purchase: int = 0
    # Sum of projected_amount over purchase budget_lines created (COP
    # net of the imported merchandise). 0.0 when file_compras was absent.
    total_purchase: float = 0.0


class PlanningCloneRequest(BaseModel):
    """Request body for POST /budget/planning/clone (spec §5.2)."""

    id_budget: int = Field(..., gt=0, description="Source budget to clone")
    nuevo_nombre: str = Field(
        ..., min_length=1, max_length=120,
        description="Name of the new scenario",
    )
    # BR-CLN-02: multiplicative factor (1 + modifier_pct/100) applied to
    # projected_amount only. Range [-100, +inf): -101 -> 422 (AC-CL-3).
    modifier_pct: float = Field(
        0.0, ge=-100.0,
        description="Percentage adjustment over projected amounts (default 0)",
    )


class PlanningCellUpdate(BaseModel):
    """Request body for PUT /budget/planning/cell/{id_budget_line} (§5.3).

    BR-CEL-01: projected_amount (and optionally description) are the ONLY
    mutable fields through this endpoint. BR-CEL-02 / ASM-12: numeric,
    finite and >= 0 (T-06); anything else -> 422.
    """

    projected_amount: float = Field(
        ..., ge=0, description="New projected amount (>= 0, finite)"
    )
    description: Optional[str] = Field(
        None, description="Optional new description (omitted = keep current)"
    )

    @field_validator("projected_amount")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        # ge=0 already rejects NaN (NaN >= 0 is False) and negatives;
        # this closes the +inf hole (T-06: finite values only).
        if not math.isfinite(v):
            raise ValueError("projected_amount must be a finite number")
        return v


class PlanningLineCreate(BaseModel):
    """Request body for POST /budget/planning/{id_budget}/line (BE-S4D §3.1).

    Reuses the enums and validator patterns of BudgetLineBase
    (app/schemas/budget/budgetLine.py); id_budget lives in the path and
    behavior invariants are enforced server-side:

    - BR-LINE-03: variable lines (behavior_type != fixed) get
      projected_amount FORCED to 0 by the CRUD layer; variable_rate is
      mandatory for them (validator below, same pattern as BudgetLineBase
      -> 422 otherwise).
    - projected_amount: ge=0 + finite (same +inf-hole closure as
      PlanningCellUpdate.must_be_finite -> 422 otherwise).
    """

    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    line_type: LineTypeEnum = Field(
        ..., description="Line type: income, expense, purchase (purchase "
                         "guards BR-PUR-02/03 apply server-side in "
                         "crud.create_planning_line: fixed + no variable "
                         "rate; a season/id_collection IS allowed on "
                         "purchases per A-01 §10.2)"
    )
    budget_date: date = Field(
        ..., description="Date when the income/expense occurs (P&L); "
                         "year must match the scenario year (BR-LINE-04)"
    )
    payment_date: Optional[date] = Field(
        None,
        description="Date when cash flows (Cash Flow). NULL -> read fallback "
                    "to budget_date (unchanged). No year restriction (R-2).",
    )
    id_collection: Optional[int] = Field(
        None, gt=0, description="FK to collection (season). Allowed on "
                                "purchase lines too (A-01 §10.2)"
    )
    projected_amount: float = Field(
        0, ge=0,
        description="Fixed lines only; server forces 0 on variable lines "
                    "(BR-LINE-03 / AC-UP-1 invariant)",
    )
    description: Optional[str] = Field(None, description="Optional description")
    behavior_type: BehaviorTypeEnum = Field(
        BehaviorTypeEnum.FIXED,
        description="Cost behavior: fixed, variable_sales, variable_receivables",
    )
    variable_rate: Optional[float] = Field(
        None, ge=0, le=1, validate_default=True,
        description="Variable rate (0-1). Required when behavior_type is not 'fixed'",
    )

    @field_validator("projected_amount")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        # Same +inf-hole closure as PlanningCellUpdate (ge=0 rejects NaN and
        # negatives; this rejects +inf).
        if not math.isfinite(v):
            raise ValueError("projected_amount must be a finite number")
        return v

    @field_validator("variable_rate")
    @classmethod
    def validate_variable_rate(cls, v, info):
        # Replicated from BudgetLineBase (BR-LINE-03: 422 when a variable
        # line arrives without its rate). validate_default=True on the
        # Field makes this fire on the omitted default too (AC-LINE-2).
        behavior = info.data.get("behavior_type")
        if behavior and behavior != BehaviorTypeEnum.FIXED and v is None:
            raise ValueError("variable_rate is required when behavior_type is not 'fixed'")
        return v


class PlanningLineUpdate(BaseModel):
    """Request body for PUT /budget/planning/line/{id_budget_line} (BE-S4D §3.2).

    Partial contract identical to LineCostRateUpdate: every field optional,
    omitted = keep current value (null also keeps: BR-LINE-07 only rejects
    fields SENT on the wrong behavior, checked via model_fields_set in the
    CRUD layer).

    BR-LINE-06: line_type and behavior_type are NOT part of this schema;
    if a client sends them, pydantic silently ignores them (extra=ignore
    default). Changing type/behavior = create a new line + delete the old
    one (D-2). FK existence, budget_date year (BR-LINE-08) and the
    behavior<->field guards (BR-LINE-07) are enforced in the CRUD layer.
    """

    id_cost_center: Optional[int] = Field(None, gt=0, description="FK to cost center")
    budget_date: Optional[date] = Field(
        None, description="Accrual date; year must match the parent scenario year"
    )
    payment_date: Optional[date] = Field(
        None, description="Cash date (no year restriction)"
    )
    id_collection: Optional[int] = Field(
        None, gt=0,
        description="FK to collection (season; valid on purchases per "
                    "A-01 §10.2)",
    )
    projected_amount: Optional[float] = Field(
        None, ge=0, description="Only on fixed lines (BR-LINE-07: 400 on variable)"
    )
    description: Optional[str] = None
    variable_rate: Optional[float] = Field(
        None, ge=0, le=1,
        description="Only on variable lines (BR-LINE-07: 400 on fixed)",
    )

    @field_validator("projected_amount")
    @classmethod
    def must_be_finite(cls, v: Optional[float]) -> Optional[float]:
        # Optional field: None = keep (omitted). When sent, ge=0 rejects
        # NaN/negatives; this closes the +inf hole (same as the Create
        # schema and PlanningCellUpdate).
        if v is not None and not math.isfinite(v):
            raise ValueError("projected_amount must be a finite number")
        return v


class PlanningScenarioRow(BaseModel):
    """One aggregated row of GET /budget/planning/ (spec §5.4, NFR-5).

    Aggregation (lines_count / totals) happens in SQL in the CRUD layer;
    this schema is just its transport shape.
    """

    id_budget: int
    budget_name: str
    budget_year: int
    is_scenario: bool
    parent_budget_name: Optional[str] = None
    status: Optional[str] = None
    lines_count: int
    total_income: float
    total_expense: float
    created_at: Optional[datetime] = None
    # BE-S6-CARRYOVER §3.1: the planning item DOES mirror model fields, so
    # the new column is exposed here too (additive key, NFR-S6-BE-2) for the
    # FE-S6 dashboard chips.
    include_carryover: bool = False


class PlanningSetTargetResult(BaseModel):
    """Response 200 for PUT /budget/planning/{id_budget}/set-target (§5.6)."""

    id_budget: int
    budget_year: int
    demoted_budget_id: Optional[int] = None


class PlanningDetail(BudgetFull):
    """GET /budget/planning/{id_budget}/detail (§5.5).

    Wrapper of BudgetFull (budget + budget_lines) plus the parent scenario
    name for the Grid Editor breadcrumb.
    """

    parent_budget_name: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# BE-S6-CARRYOVER (backend.02_16): prior-year balance carry-in
# ──────────────────────────────────────────────────────────────

class PlanningCarryoverFlag(BaseModel):
    """Request body for PUT /budget/planning/{id_budget}/carryover (§5.2).

    BR-CO-08: idempotent toggle — only include_carryover is persisted and
    re-sending the current value is a plain 200. The value is REQUIRED
    (missing / non-bool -> 422, AC-S6-BE-8). Toggling ON with no N−1
    source is legal state (the GET then reports "no_source")."""

    include_carryover: bool = Field(
        ...,
        description="Opt-in of the scenario to the prior-year carry-in "
                    "(BR-CO-01: pure preference flag, zero effect on any "
                    "other endpoint)",
    )


class PlanningCarryoverSource(BaseModel):
    """Selected N−1 scenario the carry-in is read from (BR-CO-02 winner).

    status keeps the stored lowercase casing ("active" | "closed" |
    "draft"). model_validate straight off the ORM row.
    """

    id_budget: int
    budget_name: str
    budget_year: int
    status: Optional[str] = None

    class Config:
        from_attributes = True


class PlanningCarryoverLine(BaseModel):
    """One pending balance row of the SOURCE scenario whose effective date
    coalesce(payment_date, budget_date) falls inside the TARGET year N
    (BR-CO-03). Only behavior_type=fixed rows qualify (income AND expense).

    id_budget is intentionally NOT part of the contract: the rows belong to
    the source reported in ``source`` (the FE-S6 chip marks them "←N−1",
    R-S6-1).

    BE-S7-COGS-PAYFLOW §4 (BR-CO-10): every row carries ``origin`` —
    - "line":  material row of the source (BE-S6 behavior; id_budget_line
      is the persisted id).
    - "cogs":  installment DERIVED server-side per request from a FIXED
      income row of the source (never persisted): id_budget_line = null,
      line_type = "expense", budget_date = anchor (the income row's
      budget_date, D-S7-5), payment_date = anchor + term offset — or the
      anchor itself at 100 % when the Line has no payable terms (D-S7-4) —
      and description = "Costo de venta (arrastre)".
    - "purchase": BE-S8-BUDGET-PURCHASES §5.2 (BR-PUR-05) installment
      DERIVED server-side per request from a PURCHASE row of the source
      (never persisted): same shape as "cogs" (id_budget_line = null,
      line_type = "expense", budget_date = the import date, payment_date =
      import date + term offset, single 100 % row without terms, D-S7-4)
      but amount = projected_amount × payment_pct (NO cogs_pct) and
      description = "Pago a proveedor (arrastre)". Emitted only for
      purchasing CECOs of the source (single-source rule D-4: their "cogs"
      derivation is suppressed so the supplier is never double-counted).
    """

    id_budget_line: Optional[int] = None
    id_cost_center: int
    line_type: LineTypeEnum
    budget_date: date
    payment_date: Optional[date] = None
    projected_amount: float
    description: Optional[str] = None
    origin: Literal["line", "cogs", "purchase"] = "line"

    class Config:
        from_attributes = True


class PlanningCarryoverResult(BaseModel):
    """Response 200 for GET /budget/planning/{id_budget}/carryover (§5.1).

    - enabled mirrors the include_carryover flag (never "false with lines").
    - source: winner scenario of N−1, or null when none exists.
    - lines: material (origin "line") + derived COGS installments
      (origin "cogs", BE-S7 §4) merged in stable order: effective date
      coalesce(payment_date, budget_date) ASC, then origin ("line" before
      "cogs"), then id null-safe (BR-CO-10). Dynamic re-derivation on every
      request, zero writes / snapshots (BR-CO-04/05).
    - unavailable_reason: currently only "no_source" (BR-CO-02); null when
      the feature is off or the lines were resolved.
    """

    enabled: bool
    source: Optional[PlanningCarryoverSource] = None
    lines: List[PlanningCarryoverLine] = []
    unavailable_reason: Optional[str] = None
