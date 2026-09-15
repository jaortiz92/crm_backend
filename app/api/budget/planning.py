"""
Budget Planning API Endpoints (BE-S4-BUDGET-PLANNING)

Sub-router mounted at /budget/planning (spec backend.02_12 §5). Eleven
endpoints, all JWT-protected (NFR-4):

- POST /upload               two-file all-or-nothing SIIGO ingestion (§5.1)
- POST /clone                scenario copy with % modifier over amounts (§5.2)
- PUT  /cell/{id}            single grid-cell edit (projected_amount) (§5.3)
- GET  /                     dashboard listing aggregated in SQL (§5.4)
- GET  /{id}/detail          BudgetFull wrapper + parent name for the grid (§5.5)
- PUT  /{id}/set-target      designate THE one active target of the year;
                             restricted to Gerente / Administrador (§5.6)
- POST /{id}/line            create a planning budget line (BE-S4D §3.1);
                              exactly ONE row, answer = BudgetLine
                              (BE-S7 §2 rolled the BE-S5 installment
                              expansion back)
- PUT  /line/{id}            edit the structural fields of a line (§3.2)
- DELETE /line/{id}          physically delete a line (§3.3)
- GET  /{id}/carryover       prior-year balances pending in year N (BE-S6
                              §5.1) PLUS the derived COGS payment
                              installments of BE-S7 §4 (origin "cogs")
- PUT  /{id}/carryover       toggle include_carryover; 200 with the full
                              PlanningDetail for the FE cache (BE-S6 §5.2)

BE-S4/BE-S4D added no tables/columns: scenarios are rows of `budgets`
(is_scenario, parent_budget_id) and cells are rows of `budget_lines`.
BE-S5-PAYABLE-TERMS (backend.02_15) expanded expense cells into installment
rows; BE-S7-COGS-PAYFLOW (backend.02_17 §2, D-S7-6) FULLY ROLLED that back
— expenses are paid whole again and the `line_payable_terms` catalog now
describes how the SUPPLIER of a Line's COGS is paid (consumed by the §4
carryover derivation and FE-S7, never materialized). BE-S6-CARRYOVER DOES
add one column: budgets.include_carryover (§3.1) — existing databases need
the manual ALTER documented in backend.02_16 §3.2 (also in note.md) before
deploying, since Base.metadata.create_all never alters an existing table.
The carry-in is pure READ-DERIVATION: it never writes budget_lines
(BR-CO-04/05 / D-S7-2/3).
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
    PlanningCarryoverFlag, PlanningCarryoverResult,
    PlanningCarryoverSource, PlanningCellUpdate, PlanningCloneRequest,
    PlanningDetail, PlanningLineCreate, PlanningLineUpdate,
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
            # BE-S7-COGS-PAYFLOW §2: no expansion flag anymore — the
            # builder emits ONE expense row with the file's payment_date,
            # identical to the legacy POST /budget/upload/budget-plan-
            # expense call-site (upload.py:416 never passed one either).
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


@router.post("/{id_budget}/line", response_model=BudgetLine,
             status_code=status.HTTP_201_CREATED)
def planning_create_line(
    id_budget: int,
    payload: PlanningLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create ONE planning line (BE-S4D §3.1) without re-ingesting Excel.

    JWT-only (D-7, same policy as upload/clone/cell). Validations live in
    crud.create_planning_line (BR-LINE-01/02/04/05: 404 on unknown budget
    or FKs with the §3.4 details, 400 on budget_date year mismatch, no
    status lock); variable lines get projected_amount FORCED to 0
    server-side (BR-LINE-03) and schema/format errors are 422 via
    PlanningLineCreate. Response: the full persisted BudgetLine (NFR-L-2).

    BE-S7-COGS-PAYFLOW §2 rollback: the BE-S5 §7 expansion of eligible
    fixed-expense payloads is RETIRED — this endpoint again persists
    EXACTLY ONE row honoring the payload's payment_date and answers a
    pure BudgetLine (PlanningLineCreateResult / expanded_siblings deleted;
    the FE's ``?? []`` read of the removed key is benign until FE-S7
    drops it). line_payable_terms now feeds only the derived COGS flow
    (backend.02_17 §3/§4), never manual line creation."""
    try:
        return crud.create_planning_line(db, id_budget, payload)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating planning line: {str(e)}",
        )


@router.put("/line/{id_budget_line}", response_model=BudgetLine)
def planning_update_line(
    id_budget_line: int,
    payload: PlanningLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit the structural fields of ONE line (BE-S4D §3.2): cost center,
    dates, collection, amount (fixed lines), rate (variable lines) and
    description. Partial contract: omitted = keep.

    line_type/behavior_type are NOT editable (BR-LINE-06: absent from the
    schema, silently extra-ignored; change = create + delete, D-2). The
    behavior guards raise 400 (BR-LINE-07), budget_date year 400
    (BR-LINE-08) and FKs/budget 404 inside crud.update_planning_line;
    missing line -> 404 with the BE-S4D §3.4 detail ("BudgetLine {id}
    not found", kept in the API layer per the Optional->None CRUD
    convention of update_budget_line_cell). No status lock
    (BR-LINE-05). PUT /cell stays untouched for the quick double-click
    amount edit (D-8 / NFR-L-5)."""
    try:
        db_line = crud.update_planning_line(db, id_budget_line, payload)
        if db_line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"BudgetLine {id_budget_line} not found",
            )
        return db_line

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating planning line: {str(e)}",
        )


@router.delete("/line/{id_budget_line}")
def planning_delete_line(
    id_budget_line: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Physically delete ONE line (BE-S4D §3.3, D-2: no soft flag/paper
    trash in v1). No cascades (no incoming FKs on budget_lines, spec §2)
    and no status lock (BR-LINE-05: works on draft/active/closed).
    Missing line -> 404 with the §3.4 detail (same Optional->None CRUD
    convention as planning_update_line). Response: the deleted id
    (NFR-L-3)."""
    try:
        db_line = crud.delete_planning_line(db, id_budget_line)
        if db_line is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"BudgetLine {id_budget_line} not found",
            )
        return {"deleted_id": id_budget_line}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting planning line: {str(e)}",
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


@router.get("/{id_budget}/carryover", response_model=PlanningCarryoverResult)
def planning_get_carryover(
    id_budget: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Prior-year carry-in for the scenario's cash flow (BE-S6 §5.1,
    extended by BE-S7 §4 BR-CO-09..11).

    Pure READ-DERIVATION (BR-CO-04/05 / D-S7-2): zero writes, zero
    snapshots — every request recomputes from the live N−1 scenario, so
    editing/deleting that source is reflected on the next read. Flow:

    1. Scenario existence FIRST (404 with the verbatim CRUD detail
       "Budget {id} not found", BR-CO-07 — also when the flag is OFF, §5.1).
    2. BR-CO-01 short-circuit: flag OFF -> {enabled:false, source:null,
       lines:[], unavailable_reason:null} with ZERO extra SQL (only the
       mandatory scenario read above). The BE-S7 §4 derivation NEVER runs
       here (AC-S7-BE-8).
    3. BR-CO-02 source pick (ACTIVE > CLOSED > DRAFT, updated_at DESC,
       id_budget DESC) + crud.build_carryover_payload_lines: the material
       fixed lines of the source whose effective date
       coalesce(payment_date, budget_date) falls in year N (BR-CO-03,
       origin "line", 1 SQL query) MERGED with the derived COGS payment
       installments from the source's fixed income lines (BR-CO-09,
       origin "cogs" — cost pool mirror of budgetEngine.get_pnl resolved at
       each month-end × line_payable_terms; D-S7-4 single 100 % row when
       the Line has no terms), in the BR-CO-10 order (effective date ASC,
       line before cogs, id null-safe). Query economy BR-CO-11: a constant
       handful of queries per request regardless of row counts.
    4. No candidate -> legal 200 {enabled:true, source:null, lines:[],
       unavailable_reason:"no_source"} (BR-CO-08: toggling ON never
       validates a source).

    Both income AND expense carry over as material rows; derived rows are
    always expense (a payment to the supplier). The FE-S6/FE-S7 pivots and
    labels them (BR-CO-06: the scenario's OWN out-of-year rows are NOT
    this endpoint's business)."""
    db_budget = crud.get_budget_by_id(db, id_budget)
    if db_budget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Budget {id_budget} not found",
        )

    # BR-CO-01: pure opt-in — disabled answers without touching the engine.
    if not db_budget.include_carryover:
        return PlanningCarryoverResult(
            enabled=False, source=None, lines=[], unavailable_reason=None,
        )

    source = crud.get_carryover_source_budget(
        db, db_budget.budget_year - 1, id_budget,
    )
    if source is None:
        # BR-CO-02: enabled but nothing to carry from (AC-S6-BE-4 is 200).
        return PlanningCarryoverResult(
            enabled=True, source=None, lines=[],
            unavailable_reason="no_source",
        )

    lines = crud.build_carryover_payload_lines(
        db, source.id_budget, source.budget_year, db_budget.budget_year,
    )
    return PlanningCarryoverResult(
        enabled=True,
        source=PlanningCarryoverSource.model_validate(source),
        lines=lines,
        unavailable_reason=None,
    )


@router.put("/{id_budget}/carryover", response_model=PlanningDetail)
def planning_set_carryover(
    id_budget: int,
    payload: PlanningCarryoverFlag,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle include_carryover for the scenario (BE-S6 §5.2).

    Updates ONLY the column — no year/source validation ever (BR-CO-08:
    ON without a source is a legal state FE labels with the "no_source"
    notice). Idempotent: re-sending the current value still 200s with no
    side effects (the ORM emits no UPDATE for a net-zero change). Response:
    the SAME PlanningDetail schema the GET detail endpoint returns, already
    carrying the new include_carryover — the FE-S6 refreshes its
    currentScenario cache with it (same pattern as the line PUTs).
    Missing scenario -> 404 "Budget {id} not found" (BR-CO-07); invalid
    body -> 422 via PlanningCarryoverFlag (AC-S6-BE-8)."""
    try:
        updated = crud.set_planning_carryover_flag(
            db, id_budget, payload.include_carryover,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Budget {id_budget} not found",
            )

        result = crud.get_budget_with_parent_name(db, id_budget)
        db_budget, parent_budget_name = result
        detail = PlanningDetail.model_validate(db_budget)
        detail.parent_budget_name = parent_budget_name
        return detail

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error setting carryover flag: {str(e)}",
        )


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
