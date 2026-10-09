"""
Budget Module - API Router

Aggregates all budget sub-routers under the /budget/ prefix.
"""

from fastapi import APIRouter

from .costCenter import router as cost_center_router
from .actualExpense import router as actual_expense_router
from .actualCost import router as actual_cost_router
from .budget import router as budget_router
from .budgetLine import router as budget_line_router
from .accountReceivable import router as account_receivable_router
from .paymentLedger import router as payment_ledger_router
from .budgetScenario import router as budget_scenario_router
from .accountPayable import router as account_payable_router
from .payableLedger import router as payable_ledger_router
from .lineCostRate import router as line_cost_rate_router
from .linePayableTerm import router as line_payable_term_router
from .lineInternmentRate import router as line_internment_rate_router
from .lineInternmentTerm import router as line_internment_term_router
from .commissionRate import router as commission_rate_router
from .ivaPeriod import router as iva_period_router
from .ivaSettlement import router as iva_settlement_router
from .upload import router as upload_router
from .analytics import router as analytics_router
from .planning import router as planning_router
# BE-S11-COLLABORATORS (backend.02_21 §8): maestro/planes/import/breakdown
# + parámetros laborales + catálogo de componentes. app/main.py NO cambia
# — el agregador `budget` ya estaba montado (patrón iva-period).
from .collaborator import (
    router as collaborator_router,
    labor_params_router,
    cost_components_router,
)

budget = APIRouter(prefix="/budget")

budget.include_router(cost_center_router, prefix="/cost-center", tags=["Cost Centers"])
budget.include_router(actual_expense_router, prefix="/actual-expense", tags=["Actual Expenses"])
budget.include_router(actual_cost_router, prefix="/actual-cost", tags=["Actual Costs"])
# BE-S11-COLLABORATORS (backend.02_21 §8, ENMIENDA 2026-09-28): los tres
# sub-routers de nomina VAN ANTES de budget_router: el GET legacy
# /budget/{id_budget} captura cualquier segmento literal de 2 partes
# (/budget/collaborator, /budget/labor-params, /budget/cost-components) y
# les responderia 422 'int_parsing' (input='collaborator'). Starlette resuelve
# en ORDEN de registro: el literal debe ganarle al path param. El FE-S15 usa
# las rutas SIN slash final (convencion del repo: cost-center, actual-cost).
budget.include_router(
    collaborator_router,
    prefix="/collaborator",
    tags=["Collaborators"],
)
budget.include_router(
    labor_params_router,
    prefix="/labor-params",
    tags=["Collaborators"],
)
budget.include_router(
    cost_components_router,
    prefix="/cost-components",
    tags=["Collaborators"],
)

budget.include_router(budget_router, tags=["Budgets"])
budget.include_router(budget_line_router, prefix="/line", tags=["Budget Lines"])
budget.include_router(
    account_receivable_router,
    prefix="/account-receivable",
    tags=["Accounts Receivable"],
)
budget.include_router(
    payment_ledger_router,
    prefix="/payment-ledger",
    tags=["Payment Ledger"],
)
budget.include_router(
    budget_scenario_router,
    prefix="/scenario",
    tags=["Budget Scenarios"],
)
budget.include_router(
    account_payable_router,
    prefix="/account-payable",
    tags=["Accounts Payable"],
)
budget.include_router(
    payable_ledger_router,
    prefix="/payable-ledger",
    tags=["Payable Ledger"],
)
budget.include_router(
    line_cost_rate_router,
    prefix="/line-cost-rate",
    tags=["Line Cost Rates"],
)
budget.include_router(
    line_payable_term_router,
    prefix="/line-payable-term",
    tags=["Line Payable Terms"],
)
budget.include_router(
    line_internment_rate_router,
    prefix="/line-internment-rate",
    tags=["budget"],
)
budget.include_router(
    line_internment_term_router,
    prefix="/line-internment-term",
    tags=["budget"],
)
budget.include_router(
    commission_rate_router,
    prefix="/commission-rates",
    tags=["Commission Rates"],
)
# BE-S10-IVA (spec backend.02_20 §5.9): catalogo de calendario y
# liquidacion. app/main.py NO cambia — el agregador `budget` ya estaba
# montado (pattern line-internment-rate, tags=["budget"]).
budget.include_router(
    iva_period_router,
    prefix="/iva-period",
    tags=["budget"],
)
budget.include_router(
    iva_settlement_router,
    prefix="/iva",
    tags=["budget"],
)
budget.include_router(upload_router, prefix="/upload", tags=["Budget Uploads"])
budget.include_router(analytics_router, prefix="/analytics", tags=["Budget Analytics"])
budget.include_router(
    planning_router,
    prefix="/planning",
    tags=["Budget Planning"],
)
