"""
Budget Schemas

Includes analytical / aggregation response schemas at the bottom.
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field

from .budgetLine import BudgetLine


class BudgetBase(BaseModel):
    budget_name: str = Field(..., max_length=120, description="Name of the budget")
    budget_year: int = Field(..., description="Fiscal year")
    budget_period: str = Field(
        ..., max_length=20,
        description="Period type: annual, quarterly, monthly"
    )
    id_department: Optional[int] = Field(None, gt=0, description="FK to department")
    status: Optional[str] = Field(
        "draft",
        description="Budget status: draft, active, archived"
    )
    is_scenario: Optional[bool] = Field(
        False,
        description="Whether this budget is a what-if scenario clone"
    )
    parent_budget_id: Optional[int] = Field(
        None, gt=0,
        description="FK to parent budget (for scenario clones)"
    )


class BudgetCreate(BudgetBase):
    pass


class Budget(BudgetBase):
    id_budget: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # BE-S6-CARRYOVER §3.1: additive read-only surface of the new column
    # (defaults to False so pre-column dicts keep validating). BudgetBase /
    # BudgetCreate intentionally do NOT carry it: creation never sets it and
    # the ONLY writer is PUT /budget/planning/{id_budget}/carryover.
    include_carryover: bool = False

    class Config:
        from_attributes = True


class BudgetFull(Budget):
    budget_lines: List[BudgetLine] = []


# ──────────────────────────────────────────────
# Analytical / Aggregation Response Schemas
# ──────────────────────────────────────────────

class BudgetVsActual(BaseModel):
    """Response schema for budget vs actual comparison."""
    id_cost_center: int
    cost_center_code: str
    cost_center_name: str
    budget_month: int
    budgeted_amount: float
    actual_amount: float
    variance: float
    variance_percentage: Optional[float] = None


class CashFlowProjection(BaseModel):
    """Response schema for cash flow projection."""
    payment_month: int
    expected_inflows: float
    expected_outflows: float
    net_cash_flow: float
    cumulative_cash_flow: float


class BudgetTrackingSummary(BaseModel):
    """Response schema for budget tracking aggregation."""
    id_budget: int
    budget_name: str
    total_budgeted: float
    total_actual: float
    total_variance: float
    execution_percentage: Optional[float] = None
    by_month: List[BudgetVsActual] = []


# ──────────────────────────────────────────────
# P&L (Pilar 1) Response Schemas  — spec 02_09 §4.3.2
# ──────────────────────────────────────────────

class PnLComparison(BaseModel):
    actual: Optional[float] = None      # Optional: en modo corte hay lineas no filtrables (null)
    budget: Optional[float] = None      # None = sin presupuesto aplicable / no cortable
    variance: Optional[float] = None    # convencion de favorabilidad (D-4)
    variance_pct: Optional[float] = None


class PnLProfit(BaseModel):
    actual: Optional[float] = None
    budget: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    margin_pct: Optional[float] = None          # real (A-9)
    margin_pct_budget: Optional[float] = None   # presupuestado (aditivo, no rompe el contrato del HSpec)


class OpexBreakdownItem(BaseModel):
    category: str        # expense_type del libro auxiliar
    actual: float


class PnLOpex(PnLComparison):
    breakdown: Optional[List[OpexBreakdownItem]] = None   # solo con include_breakdown=true


class PnLStatement(BaseModel):
    revenues: PnLComparison
    cogs: PnLComparison
    gross_profit: PnLProfit
    opex: PnLOpex
    operating_profit: PnLProfit


class CogsBudgetTraceItem(BaseModel):
    id_cost_center: int
    cost_center_code: Optional[str] = None       # denormalizado para tooltips de UI
    id_line: Optional[int] = None                # linea del CECO (null = sin linea)
    pct: float                                   # tasa aplicada (0-100)
    source: str                                  # "line" | "global" (D-6)
    income_budget: float                         # ingreso presupuestado del CECO en el periodo
    cogs_contribution: float                     # income_budget * pct / 100 (2 dec)


class PnLMeta(BaseModel):
    mode: str                                    # "consolidated" | "slice"
    budget_source: Optional[dict] = None         # {id_budget, budget_name, status}
    filters: dict                                # eco exacto de los query params recibidos
    not_filterable: List[str] = []               # p.ej. "revenues (no cost-center dimension)"
    cogs_budget_trace: List[CogsBudgetTraceItem] = []   # D-6: auditoria CECO-por-CECO de cogs.budget
    warnings: List[str] = []                     # BR-15: tasas faltantes, ano cruzado, NC sin referencia


class PnLResponse(BaseModel):
    period: dict          # {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}  — mismo shape que el HSpec
    pnl_statement: PnLStatement
    meta: PnLMeta


# ──────────────────────────────────────────────
# Cash Flow (Pilar 2) Response Schemas  — spec 02_10 §4.3
# ──────────────────────────────────────────────

class CashFlowPoint(BaseModel):
    period: str                        # label ISO del bucket (BR-34; puede ser anterior a
                                       # date_from en el primer bucket semanal parcial)
    status: str                        # "actual" | "projected" (D-3/BR-24)
    inflows: float                     # >= 0
    outflows: float                    # <= 0 (convencion del JSON de ejemplo del HSpec)
    net_flow: float                    # = inflows + outflows (nunca se "resta el negativo")
    accumulated_balance: float         # running-sum desde starting_balance (BR-35)


class CashFlowSummary(BaseModel):
    starting_balance: float
    ending_balance: float              # = starting + SUM(net_flow)  (invariante BR-35)
    net_flow: float                    # suma de net_flow de toda la ventana


class CashFlowMeta(BaseModel):
    granularity: str
    cutoff: str                        # fecha del punto de inflexion realmente usada (BR-37)
    initial_balance_source: str        # "provided" | "derived_from_ledger" (D-4)
    outflow_source: str                # eco efectivo (D-1)
    overdue_as: str                    # eco efectivo (D-2)
    budget_source: Optional[dict] = None   # {id_budget, budget_name, status} | null (D-7)
    overdue_outflows: float = 0.0      # total AP clampado/excluido segun modo
    filters: dict                      # eco de los query params efectivos (BR-39)
    warnings: List[str] = []


class CashFlowResponse(BaseModel):
    summary: CashFlowSummary
    time_series: List[CashFlowPoint]
    meta: CashFlowMeta


# ──────────────────────────────────────────────
# Commission Engine (Pilar 3) Response Schemas  — spec 02_11 §4.4
# ──────────────────────────────────────────────

class CommissionRateTrace(BaseModel):
    id_commission_rate: Optional[int] = None   # NULL cuando no habia tasa (pct=0)
    id_line: Optional[int] = None              # NULL = balde global / sin-linea
    line_name: Optional[str] = None
    commission_pct: float                      # 0.0 si no hubo tasa aplicable (A-11)
    base_net: float                            # porcion de la base neta en este tramo
    commission_earned: float                   # round(base_net * pct / 100, 2)


class CommissionDetailRow(BaseModel):
    id_payment_ledger: int                     # traza directa al libro (soporte de pago)
    receipt_number: str
    payment_date: date
    invoice_number: Optional[str] = None       # NULL en ruta anticipo (D-2 paso 3)
    collected_amount: float                    # bruto recaudado, SIEMPRE >= 0 (D-6)
    commission_base: float                     # neto de IVA: collected / (1 + TAX_RATE) (D-1)
    commission_rate_applied: float             # pct echo: tasa unica o blend (BR-47)
    rate_details: List[CommissionRateTrace]    # traza conciliable renglon a renglon
    commission_earned: float                   # = SUM(rate_details.commission_earned)


class CommissionSellerBlock(BaseModel):
    id_seller: int
    seller_name: str                           # users.first_name + ' ' + last_name
    total_collected: float                     # suma collected_amount de sus renglones
    total_commission: float                    # suma commission_earned de sus renglones
    details: List[CommissionDetailRow]


class CommissionSummary(BaseModel):
    total_collected_base: float                # Σ bruto de renglones ATRIBUIBLES (nombre HSpec)
    total_net_base: float                      # Σ commission_base (aditivo, gobernanza D-1)
    total_commissions_calculated: float        # Σ earned (invariante BR-48)
    total_unattributed_collected: float = 0.0  # Σ bruto no-atribuible (BR-44)
    unattributed_count: int = 0


class CommissionMeta(BaseModel):
    business_period: Optional[str] = None      # "2026-09" si la ventana deriva de periodo; else None
    period_source: str                         # "period_param" | "explicit_dates" (D-5)
    tax_rate_used: float                       # valor efectivo de TAX_RATE al resolver (D-1)
    filters: dict                              # eco de los 5 query params efectivos (BR-52)
    warnings: List[str] = []


class CommissionResponse(BaseModel):
    period: dict                               # {"from": iso, "to": iso} ventana EFECTIVA (HSpec literal)
    summary: CommissionSummary
    commissions_by_seller: List[CommissionSellerBlock]
    meta: CommissionMeta
