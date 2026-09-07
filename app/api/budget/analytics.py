"""
Analytics API Endpoints

Cash flow projection, budget vs actual tracking, and scenario cloning.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import (
    Budget,
    BudgetVsActual,
    CashFlowProjection,
    BudgetTrackingSummary,
    PnLResponse,
)
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions
from app.services.budgetEngine import BudgetEngine

router = APIRouter()


@router.get("/cash-flow-projection", response_model=List[CashFlowProjection])
def get_cash_flow_projection(
    budget_year: int = Query(..., description="Fiscal year for projection"),
    id_budget: Optional[int] = Query(None, description="Specific budget ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Project cash flow by crossing accounts receivable due dates
    against import calendars. Returns monthly inflows, outflows,
    net cash flow and cumulative cash flow (Cash Runway).
    """
    engine = BudgetEngine(db)
    return engine.project_cash_flow(budget_year=budget_year, id_budget=id_budget)


@router.get("/budget-vs-actual", response_model=List[BudgetVsActual])
def get_budget_vs_actual(
    id_budget: int = Query(..., description="Budget ID to compare"),
    id_cost_center: Optional[int] = Query(None, description="Filter by cost center"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Filter by month"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compare budget projections against actual execution.
    Returns aggregated values by month and cost center with variance analysis.
    """
    # TODO: Implement via BudgetEngine service
    return []


@router.get("/tracking/{id_budget}", response_model=BudgetTrackingSummary)
def get_budget_tracking_summary(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a complete budget tracking summary with total budgeted,
    total actual, variance and execution percentage.
    """
    # TODO: Implement via BudgetEngine service
    return BudgetTrackingSummary(
        id_budget=id_budget,
        budget_name="",
        total_budgeted=0,
        total_actual=0,
        total_variance=0,
    )


@router.post("/clone-for-scenario/{id_budget}", response_model=Budget)
def clone_budget_for_scenario(
    id_budget: int,
    scenario_name: str = Query(..., description="Name for the scenario clone"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Clone a budget into a sandbox for what-if simulation.
    Creates a new budget with is_scenario=True and parent_budget_id
    pointing to the original. All budget lines are duplicated.
    """
    # TODO: Implement via BudgetEngine service
    return crud.get_budget_by_id(db, id_budget)


@router.get("/pnl", response_model=PnLResponse)
def get_pnl(
    date_from: date = Query(..., description="Period start (inclusive, accrual dates)"),
    date_to: date = Query(..., description="Period end (inclusive; governs budget year and rate validity)"),
    id_budget: Optional[int] = Query(None, description="Explicit budget ID (also allows scenario clones). Default: active budget of year(date_to)"),
    id_cost_center: Optional[int] = Query(None, description="Filter COGS/OPEX/budget by cost center (does NOT apply to revenues)"),
    id_line: Optional[int] = Query(None, description="Slice revenues/COGS by product line (brand mapping)"),
    id_reference: Optional[int] = Query(None, description="Slice revenues/COGS by product reference"),
    include_breakdown: bool = Query(False, description="Add opex.breakdown by expense_type (actual only)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pilar 1 - Accrual P&L: actual vs budget vs variance with margins."""
    # Pre-engine validations (spec §6.1): E-1 on the range, E-2 on the FKs.
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from must be on or before date_to",
        )
    if id_budget is not None and crud.get_budget_by_id(db, id_budget) is None:
        Exceptions.register_not_found("Budget", id_budget)
    if id_cost_center is not None and crud.get_cost_center_by_id(db, id_cost_center) is None:
        Exceptions.register_not_found("CostCenter", id_cost_center)
    if id_line is not None and crud.get_line_by_id(db, id_line) is None:
        Exceptions.register_not_found("Line", id_line)
    if id_reference is not None and crud.get_reference(db, id_reference) is None:
        Exceptions.register_not_found("Reference", id_reference)

    try:
        engine = BudgetEngine(db)
        return engine.get_pnl(
            date_from=date_from, date_to=date_to, id_budget=id_budget,
            id_cost_center=id_cost_center, id_line=id_line, id_reference=id_reference,
            include_breakdown=include_breakdown,
        )
    except HTTPException:
        raise
    except Exception as e:  # E-8: any other DB/parse failure (analítica pattern)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error computing P&L: {str(e)}",
        )
