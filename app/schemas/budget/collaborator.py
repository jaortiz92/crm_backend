"""
Collaborator Schemas (BE-S11-COLLABORATORS, spec backend.02_21 §9)

Wire contract mirror of the payroll module. D-S11-2: low-cardinality enums
are ``Literal`` validated strings (NO Postgres enum types). D-S11-4/BR-06:
money fields are ``Decimal`` end-to-end — NEVER float — so the ±0.01 per
seat tolerance and the ROUND_HALF_UP quantization of the engine survive
serialization (FastAPI's jsonable_encoder emits Decimal as its string
form, exact).

D-S11-7 / BR-14 (Ley 1581/2012): CollaboratorOut denormalizes the CURRENT
salary plan. When the caller's role is outside COLLAB_VIEW_ROLES the API
layer nulls the four economic fields and sets ``salary_masked: true`` —
the master keeps browsing, the salary does not leak (AC-SEG-1).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# D-S11-2 vocabularies (single source of truth for models+API).
DocType = Literal["CC", "CE", "NIT"]
ContractType = Literal[
    "open_ended", "fixed_term", "work_or_service", "service_provision",
]
CollaboratorStatus = Literal["active", "terminated"]
RiskClass = Literal["I", "II", "III", "IV", "V"]
Layer = Literal["CAJA", "PROVISION"]

_ZERO = Decimal("0.00")


# ──────────────────────────────────────────────────
# Master (collaborators) — §4.1
# ──────────────────────────────────────────────────

class CollaboratorCreate(BaseModel):
    """Manual alta (POST /budget/collaborator): master fields PLUS the
    first salary plan (salary lives in plans, §4.2 — the payload is flat
    for UI ergonomics and the API splits it)."""

    doc_type: DocType = Field("CC", description="CC | CE | NIT")
    doc_value: str = Field(..., min_length=1, max_length=20,
                           description="Natural upsert key (unique)")
    full_name: str = Field(..., min_length=1, max_length=150)
    id_cost_center: int = Field(..., gt=0, description="Single CECO (A-09)")
    contract_type: ContractType = Field(
        ..., description="open_ended | fixed_term | work_or_service | "
                         "service_provision (D-S11-2)"
    )
    hire_date: date
    termination_date: Optional[date] = Field(
        None, description="Past date => terminated + liquidation (BR-LIQ-01)"
    )
    risk_class: Optional[RiskClass] = Field(
        None, description="ARL I..V; NULL => arl_default_class param"
    )
    id_collection: Optional[int] = Field(None, gt=0,
                                         description="Temporada default")
    # backend.02_27 §4: FALSE => the motor never emits C_PENSION for
    # this collaborator. Default TRUE = current behavior.
    pays_pension: bool = Field(
        True, description="Cotiza pensión: FALSE suprime el asiento "
                          "patronal de pensión (C_PENSION)"
    )
    notes: Optional[str] = None
    # First salary plan (stored in collaborator_salary_plans, §4.2)
    salary: Optional[Decimal] = Field(None, gt=0, description="COP/mes (honorarios en servicio); None => sin plan inicial: la UI FE-S15 encadena POST /{id}/salary-plan")
    allowance_salary: Decimal = Field(_ZERO, ge=0,
                                      description="Asignación salarial fija")
    allowance_non_salary: Decimal = Field(
        _ZERO, ge=0,
        description="Asignación NO salarial: jamás IBC ni base de "
                    "prestaciones (BR-11)",
    )
    is_integral: bool = Field(False, description="Salario integral (§5.1)")
    valid_from: Optional[date] = Field(
        None, description="Vigencia del plan; default = hoy (o hire_date "
                          "si es posterior)"
    )


class CollaboratorUpdate(BaseModel):
    """PUT campos maestro — salary is NOT editable here (§9: the salary
    change route is POST /{id}/salary-plan which appends a vigencia
    instead of mutating history, BR-02)."""

    doc_type: Optional[DocType] = None
    doc_value: Optional[str] = Field(None, min_length=1, max_length=20)
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    id_cost_center: Optional[int] = Field(None, gt=0)
    contract_type: Optional[ContractType] = None
    hire_date: Optional[date] = None
    termination_date: Optional[date] = None
    risk_class: Optional[RiskClass] = None
    id_collection: Optional[int] = Field(None, gt=0)
    # backend.02_27 §4: None = leave the current flag untouched
    pays_pension: Optional[bool] = None
    notes: Optional[str] = None


class CollaboratorOut(BaseModel):
    """Master row + current plan denormalized, masked per D-S11-7."""

    model_config = ConfigDict(from_attributes=True)

    id_collaborator: int
    doc_type: str
    doc_value: str
    full_name: str
    id_cost_center: int
    contract_type: str
    status: str
    hire_date: date
    termination_date: Optional[date] = None
    risk_class: Optional[str] = None
    id_collection: Optional[int] = None
    notes: Optional[str] = None
    # backend.02_27 §4: default True so OLD rows (pre-ALTER, or masked
    # responses built before the column existed) answer the flag.
    pays_pension: bool = Field(
        True, description="Cotiza pensión (motor: C_PENSION solo si True)"
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    cost_center_name: Optional[str] = None
    # ── current salary plan (NULL when masked or without plan) ──
    salary: Optional[Decimal] = None
    allowance_salary: Optional[Decimal] = None
    allowance_non_salary: Optional[Decimal] = None
    is_integral: Optional[bool] = None
    valid_from: Optional[date] = None
    salary_masked: bool = Field(
        False, description="True = role outside COLLAB_VIEW_ROLES: the "
                           "four economic fields above are null (D-S11-7)"
    )
    # -- history: populated ONLY in GET /{id} (detail); None in lists
    #    (avoids N+1). FE-S15 reads it for the read-only plans table.
    salary_plans: Optional[List["SalaryPlanOut"]] = None


class CollaboratorListResponse(BaseModel):
    """GET /budget/collaborator → {total, items[]} (§9)."""

    total: int
    items: List[CollaboratorOut]


# ──────────────────────────────────────────────────
# Salary plans (collaborator_salary_plans) — §4.2
# ──────────────────────────────────────────────────

class SalaryPlanCreate(BaseModel):
    """POST /{id}/salary-plan: new vigencia; closes the previous open
    plan (valid_to = valid_from - 1) — never edits closed history
    (BR-02/BR-COLLAB-02)."""

    salary: Decimal = Field(..., gt=0)
    allowance_salary: Decimal = Field(_ZERO, ge=0)
    allowance_non_salary: Decimal = Field(_ZERO, ge=0,
                                          description="Never in IBC (BR-11)")
    is_integral: bool = False
    valid_from: date


class SalaryPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_salary_plan: int
    id_collaborator: int
    salary: Decimal
    allowance_salary: Decimal
    allowance_non_salary: Decimal
    is_integral: bool
    valid_from: date
    valid_to: Optional[date] = None
    created_at: Optional[datetime] = None


CollaboratorOut.model_rebuild()  # resolves the "SalaryPlanOut" forward ref


# ──────────────────────────────────────────────────
# Actions — §9
# ──────────────────────────────────────────────────

class TerminateRequest(BaseModel):
    """POST /{id}/terminate → status terminated + LIQ seats (§5.5)."""

    termination_date: date


class RecalculateRequest(BaseModel):
    """POST /budget/collaborator/recalculate: re-runs the motor over the
    months of the scenario year of ``month`` (R-13 idempotent replacement)
    for one collaborator, one cost center or all of them."""

    month: str = Field(
        ..., pattern=r"^\d{4}-\d{2}$",
        description="Anchor month YYYY-MM; the recalculation covers the "
                    "whole year of the scenario",
    )

    @field_validator("month")
    @classmethod
    def _validate_month(cls, v: str) -> str:
        month_no = int(v.split("-")[1])
        if not 1 <= month_no <= 12:
            raise ValueError("month must be between 01 and 12")
        return v

    id_collaborator: Optional[int] = Field(None, gt=0)
    id_cost_center: Optional[int] = Field(None, gt=0)


class RecalculateResult(BaseModel):
    replaced_lines: int
    created_lines: int
    collaborators: int = 0
    warnings: List[str] = []


class CollaboratorDeleteResult(BaseModel):
    """200 of DELETE /budget/collaborator/{id} (S12-COLLAB-DELETE):
    summary of the physical cascade for audit + FE success toast."""

    id_collaborator: int
    full_name: str
    deleted_salary_plans: int = 0
    deleted_provision_accruals: int = 0
    deleted_budget_lines: int = 0


# ──────────────────────────────────────────────────
# Import (plantilla de nómina) — §6/§9
# ──────────────────────────────────────────────────

class CollaboratorImportResult(BaseModel):
    """200 of POST /budget/collaborator/import (§9, T-05 single commit)."""

    imported: int = Field(..., description="Valid data rows processed")
    created: int = Field(..., description="New collaborators (alta)")
    updated: int = Field(..., description="Existing with new/changed plan")
    no_change: int = Field(..., description="Identical rows (R-07 no-op)")
    generated_lines: int = Field(
        ..., description="budget_lines materialized by the motor (R-09)"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-blocking notes (e.g. year without active "
                    "scenario: accruals kept, seats not materialized)",
    )


# ──────────────────────────────────────────────────
# Labor parameters & ARL rates — §4.3/§4.4, §9
# ──────────────────────────────────────────────────

class LaborParameterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vigencia: int
    key: str
    value: str


class ArlRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vigencia: int
    risk_class: str
    # Decimal → exact JSON string via the encoder (D-S11-4: no float).
    rate: Decimal


class LaborParameterUpsert(BaseModel):
    """PUT /budget/labor-params {vigencia, values:{key:value}} (§9). The
    optional arl_rates companion exists so an annual vigencia (NFR-06)
    can be created in one call — rates without their own endpoint in §9
    would otherwise force raw SQL."""

    vigencia: int = Field(..., ge=2000, le=2100)
    values: Dict[str, str] = Field(default_factory=dict)
    arl_rates: Dict[RiskClass, Decimal] = Field(default_factory=dict)


class LaborParamsResponse(BaseModel):
    vigencia: int
    params: Dict[str, str] = Field(default_factory=dict)
    arl_rates: Dict[str, Decimal] = Field(default_factory=dict)


# ──────────────────────────────────────────────────
# Cost components catalog — §4.5
# ──────────────────────────────────────────────────

class CostComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    layer: str
    formula_key: Optional[str] = None
    is_legal: bool
    is_active: bool
    payment_date_key: Optional[str] = None


# ──────────────────────────────────────────────────
# Breakdown & provisions — §9
# ──────────────────────────────────────────────────

class BreakdownComponentOut(BaseModel):
    """One engine seat of the month. ``kind`` is an additive key that
    lets the FE separate causacion (accrual) from payment seats when the
    same code appears twice in a legal payment month (June PRIMA caused +
    prima ene-jun paid)."""

    code: str
    name: str
    layer: Layer
    amount: Decimal
    payment_date: Optional[date] = None
    kind: Literal["accrual", "payment", "liquidation", "caja"] = "caja"
    liq_for: Optional[str] = Field(
        None, description="For kind=liquidation: accrued component whose "
                          "unsettled balance this LIQ seat absorbs"
    )


class BreakdownOut(BaseModel):
    """GET /{id}/breakdown?month=YYYY-MM (§9)."""

    id_collaborator: int
    month: str
    components: List[BreakdownComponentOut] = []
    total_caja: Decimal = _ZERO
    total_provision: Decimal = _ZERO
    params_vigencia: int


class ProvisionBalanceOut(BaseModel):
    component_code: str
    accrued: Decimal = _ZERO
    paid: Decimal = _ZERO
    balance: Decimal = _ZERO


class ProvisionsOut(BaseModel):
    """GET /{id}/provisions → balances per component (§9, D-S11-3)."""

    id_collaborator: int
    balances: List[ProvisionBalanceOut] = []


# ── Materialization status (Opcion A: banner del editor de escenario)

class MaterializationStatusOut(BaseModel):
    """GET /budget/collaborator/materialization-status (BE-S11 enmienda).

    COUNTS ONLY — no salary, no names, no amounts cross this endpoint,
    hence the plain-auth gate (any authenticated user) instead of
    COLLAB_VIEW_ROLES: the data needed to warn is aggregate-safe.
    needs_materialization = hay colaboradores con plan abierto y CERO
    lineas del motor en el escenario activo del ano."""

    year: int
    scenario_id_budget: Optional[int] = None
    active_collaborators: int
    collaborators_with_open_plan: int
    payroll_lines_in_scenario: int
    needs_materialization: bool
