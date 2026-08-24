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
from .upload import router as upload_router
from .analytics import router as analytics_router

budget = APIRouter(prefix="/budget")

budget.include_router(cost_center_router, prefix="/cost-center", tags=["Cost Centers"])
budget.include_router(actual_expense_router, prefix="/actual-expense", tags=["Actual Expenses"])
budget.include_router(actual_cost_router, prefix="/actual-cost", tags=["Actual Costs"])
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
budget.include_router(upload_router, prefix="/upload", tags=["Budget Uploads"])
budget.include_router(analytics_router, prefix="/analytics", tags=["Budget Analytics"])
