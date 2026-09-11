"""
Budget Planning API Endpoints (BE-S4-BUDGET-PLANNING)

Sub-router mounted at /budget/planning (spec backend.02_12 §5). Six
endpoints, all JWT-protected (NFR-4):

- POST /upload               two-file all-or-nothing SIIGO ingestion (§5.1)
- POST /clone                scenario copy with % modifier over amounts (§5.2)
- PUT  /cell/{id}            single grid-cell edit (projected_amount) (§5.3)
- GET  /                     dashboard listing aggregated in SQL (§5.4)
- GET  /{id}/detail          BudgetFull wrapper + parent name for the grid (§5.5)
- PUT  /{id}/set-target      designate THE one active target of the year;
                             restricted to Gerente / Administrador (§5.6)

Zero new tables/columns: scenarios are rows of `budgets` (is_scenario,
parent_budget_id) and cells are rows of `budget_lines`.
"""

from io import BytesIO
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status,
)
from sqlalchemy.orm import Session

import app.crud as crud
from app import get_db
from app.api.utils import Exceptions
from app.core.auth import get_current_user
from app.schemas import (
    Budget, BudgetCreate, BudgetLine, BudgetLineCreate, User,
    PlanningCellUpdate, PlanningCloneRequest, PlanningDetail,
    PlanningScenarioRow, PlanningSetTargetResult, PlanningUploadResult,
)
from app.services.budgetPlanningIngestion import (
    BudgetYearMismatchError,
    build_expense_line_records,
    build_income_line_records,
)
from app.utils.templates import BudgetTemplates

router = APIRouter()

# PQ-1 (resolved): real CRM roles. set-target is management-only;
# "Financiero" may upload/clone/edit cells but NOT designate the target.
TARGET_ADMIN_ROLES = {"Gerente", "Administrador"}


def require_target_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Role gate for PUT /budget/planning/{id}/set-target (§5.6 / ASM-9).

    Resolves the role name from the authenticated user; raises 403 with no
    mutation for anybody outside {Gerente, Administrador}.
    """
    role_name = getattr(getattr(current_user, "role", None), "role_name", None)
    if role_name not in TARGET_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only users with role Gerente or Administrador can "
                "designate the active budget target"
            ),
        )
    return current_user


@router.post("/upload", response_model=PlanningUploadResult,
             status_code=status.HTTP_201_CREATED)
async def planning_upload(
    scenario_name: str = Form(..., max_length=120),
    budget_year: int = Form(..., ge=2000, le=2100),
    budget_period: str = Form("ANUAL", max_length=20),
    id_department: Optional[int] = Form(None),
    file_ingresos: UploadFile = File(...),
    file_gastos: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create the Base scenario from the two official SIIGO request files
    (§5.1). ONE transaction for Budget + both files' lines (BR-ING-01):
    any failure — unknown cost center, year mismatch, duplicate name —
    rolls everything back (no budget row survives).

    Formats are the already-supported long SIIGO layouts processed by
    BudgetTemplates.process_budget_plan_income/expense (ASM-10): the file
    header must be in row 8 and income rows expand through
    line_payment_rules exactly like the legacy uploads (BR-ING-05,
    shared builder in app/services/budgetPlanningIngestion.py).
    """
    ingresos_bytes = BytesIO(await file_ingresos.read())
    gastos_bytes = (
        BytesIO(await file_gastos.read()) if file_gastos is not None else None
    )

    try:
        # BR-ING-04: uniqueness (budget_year, budget_name).
        if crud.planning_name_exists_in_year(db, budget_year, scenario_name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Scenario name already exists for year {budget_year}",
            )

        # BR-ING-02: base scenario = draft, is_scenario=False, no parent.
        # Add+flush only — the single commit happens at the end (T-05).
        new_budget = crud.create_scenario_budget(db, BudgetCreate(
            budget_name=scenario_name,
            budget_year=budget_year,
            budget_period=budget_period,
            id_department=id_department,
            status="draft",
            is_scenario=False,
            parent_budget_id=None,
        ))

        # Phase A — incomes (mandatory, §4.1).
        etl = BudgetTemplates(ingresos_bytes)
        etl.process_budget_plan_income()
        income_records = etl.dataframe_to_records()
        income_lines, missing_cost_centers = build_income_line_records(
            db, income_records, new_budget.id_budget, budget_year=budget_year,
        )

        # Phase B — expenses (optional: an income-only scenario is valid).
        expense_lines: List[dict] = []
        if gastos_bytes is not None:
            etl = BudgetTemplates(gastos_bytes)
            etl.process_budget_plan_expense()
            expense_records = etl.dataframe_to_records()
            expense_lines, missing_exp = build_expense_line_records(
                db, expense_records, new_budget.id_budget,
                budget_year=budget_year,
            )
            missing_cost_centers = missing_cost_centers + missing_exp

        # BR-ING-03: reject with the full list; nothing is persisted.
        if missing_cost_centers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Cost centers not found",
                    "missing_cost_centers": missing_cost_centers,
                },
            )

        all_lines = income_lines + expense_lines
        if all_lines:
            lines_to_create = [BudgetLineCreate(**data) for data in all_lines]
            # ONLY commit of the operation: budget + both files' lines.
            crud.create_budget_lines_bulk(db, lines_to_create)
        else:
            db.commit()

        return PlanningUploadResult(
            id_budget=new_budget.id_budget,
            scenario_name=scenario_name,
            budget_year=budget_year,
            lines_income=len(income_lines),
            lines_expense=len(expense_lines),
            total_income=sum(
                float(line["projected_amount"]) for line in income_lines
            ),
            # Variable expense rows carry projected_amount = 0 (their rate
            # lives in variable_rate): the sum is the FIXED expense total.
            total_expense_fixed=sum(
                float(line["projected_amount"]) for line in expense_lines
            ),
            # Extra lines produced by payment-rule expansion (§5.1).
            payment_rules_expansions=len(income_lines) - len(income_records),
        )

    except HTTPException:
        db.rollback()
        raise
    except BudgetYearMismatchError as e:
        # BR-ING-06: rows outside the declared year -> structured 400 (§4.3).
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Rows outside declared budget_year",
                "found_years": e.found_years,
            },
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing planning upload: {str(e)}",
        )


@router.post("/clone", response_model=Budget,
             status_code=status.HTTP_201_CREATED)
def planning_clone(
    payload: PlanningCloneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clone a budget (base, scenario, clone of a clone or the active
    target — BR-CLN-04) into a new draft scenario.

    projected_amount is scaled by (1 + modifier_pct/100) without rounding
    (BR-CLN-02); variable_rate is copied UNSCALED (BR-CLN-03). Source is
    never mutated. 404 on unknown source, 400 on duplicate name in the
    year (BR-ING-04 / BR-CLN-05)."""
    try:
        source = crud.get_budget_by_id(db, payload.id_budget)
        if source is None:
            Exceptions.register_not_found("Budget", payload.id_budget)

        if crud.planning_name_exists_in_year(
            db, source.budget_year, payload.nuevo_nombre
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Scenario name already exists for year "
                    f"{source.budget_year}"
                ),
            )

        return crud.clone_budget_with_modifier(
            db, source, payload.nuevo_nombre, payload.modifier_pct,
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cloning budget: {str(e)}",
        )


@router.put("/cell/{id_budget_line}", response_model=BudgetLine)
def planning_update_cell(
    id_budget_line: int,
    payload: PlanningCellUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit ONE budget line (grid cell): only projected_amount — plus
    description when provided — changes (BR-CEL-01). Dates, type, behavior,
    rate, cost center and budget id are immutable here. Validated finite
    and >= 0 (BR-CEL-02/ASM-12, 422 otherwise). No state lock and no
    concurrency control: last-write-wins (BR-CEL-03/ASM-7). The legacy
    whole-object PUT /budget/line/{id} is untouched (BR-CEL-04)."""
    try:
        db_line = crud.update_budget_line_cell(
            db,
            id_budget_line,
            payload.projected_amount,
            payload.description,
        )
        if db_line is None:
            Exceptions.register_not_found("BudgetLine", id_budget_line)
        return db_line

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating budget line cell: {str(e)}",
        )


@router.get("/", response_model=List[PlanningScenarioRow])
def planning_list(
    budget_year: Optional[int] = Query(
        None, description="Filter by fiscal year (optional)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard listing of scenarios (bases + alternatives) aggregated in
    SQL (NFR-5, §5.4): line counts and income/expense totals per budget via
    one grouped subquery; parent name via self join. No pagination in MVP.

    Order: budget_year DESC, status (active > draft > closed), id_budget
    ASC."""
    return crud.get_planning_scenarios(db, budget_year=budget_year)


@router.get("/{id_budget}/detail", response_model=PlanningDetail)
def planning_detail(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full scenario for the Grid Editor (§5.5): wrapper of the existing
    BudgetFull payload (budget + budget_lines) plus parent_budget_name.
    The cc×month pivot is assembled client-side (Opción 1, no matrix
    endpoint in the backend). 404 if the budget does not exist."""
    result = crud.get_budget_with_parent_name(db, id_budget)
    if result is None:
        Exceptions.register_not_found("Budget", id_budget)
    db_budget, parent_budget_name = result

    detail = PlanningDetail.model_validate(db_budget)
    detail.parent_budget_name = parent_budget_name
    return detail


@router.put("/{id_budget}/set-target",
            response_model=PlanningSetTargetResult)
def planning_set_target(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_target_admin),
):
    """Designate THE active target of a year (§5.6). Restricted to
    Gerente/Administrador (require_target_admin, 403 otherwise, no
    mutation).

    One transaction (BR-TGT-01): the chosen budget becomes status='active'
    and every OTHER active budget of the same budget_year becomes
    'closed' (invariant: at most one active per year, guaranteed here —
    not in the DB). Idempotent: re-setting the current target returns 200
    with no changes (BR-TGT-02). The demoted budget keeps its lines and
    can be reactivated later (closed is not terminal, §3.1)."""
    try:
        result = crud.set_active_target(db, id_budget)
        if result is None:
            Exceptions.register_not_found("Budget", id_budget)
        return result

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error setting active target: {str(e)}",
        )
