"""
Analytics API Endpoints

Cash flow projection, budget vs actual tracking, and scenario cloning.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.schemas import User
from app.schemas.budget import (
    Budget,
    BudgetVsActual,
    CashFlowProjection,
    BudgetTrackingSummary,
)
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
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
