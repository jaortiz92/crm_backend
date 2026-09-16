"""
Budget Planning CRUD Operations (BE-S4-BUDGET-PLANNING)

Legacy ``db.query(Model).filter(...)`` style (T-03). The functions here back
the /budget/planning endpoints (spec backend.02_12 §5): SQL-level scenario
listing, clone with percentage modifier, single-cell edit, and the
"one active target per year" transaction (BR-TGT-01).

BE-S4D (backend.02_13 §4) adds the planning LINE manager operations:
``create_planning_line`` / ``update_planning_line`` / ``delete_planning_line``
(BR-LINE-01..08). BE-S5-PAYABLE-TERMS (backend.02_15 §6/§7) extended
``create_planning_line`` with the payable-terms installment expansion; that
extension was FULLY ROLLED BACK by BE-S7-COGS-PAYFLOW (backend.02_17 §2,
D-S7-6) and the function again creates exactly ONE row and returns ONLY it
(same transaction and validations as BE-S4D). BE-S6-CARRYOVER
(backend.02_16 §4) appended the READ-DERIVATION helpers
``get_carryover_source_budget`` / ``get_carryover_lines`` (BR-CO-02/03,
NFR-S6-BE-1: 2 SQL queries max per enabled GET) plus the toggle
``set_planning_carryover_flag`` (BR-CO-08), and mirrored the new
``include_carryover`` column in ``get_planning_scenarios``. BE-S7 §4
(backend.02_17, BR-CO-09..11) adds ``get_carryover_cogs_lines`` (per-request
derivation of COGS supplier-payment installments from the source's FIXED
income lines, read-only) and ``build_carryover_payload_lines`` (material +
derived merged in BR-CO-10 order). The 400 guards raise
``fastapi.HTTPException`` inside this layer like ``crud/budget/lineCostRate.py``
does; "line not found" keeps the
existing planning convention (return ``None`` -> the API layer raises the
404 via ``Exceptions.register_not_found``, exactly like
``update_budget_line_cell``). BE-S8-BUDGET-PURCHASES (backend.02_18 §5.1)
adds the third line type ``purchase``: shape guards on create/update
(BR-PUR-02..04 — 400 with a ``{reason}`` detail payload, ``payment_date``
silently NULLed on create), the deterministic ``get_carryover_lines``
exclusion (BR-CO-12), ``get_carryover_purchase_lines`` (BR-PUR-05:
supplier installments read-derived from the source's purchase rows ×
``line_payable_terms``, same §4 semantics as the COGS derivation) and the
single-source switch of ``build_carryover_payload_lines`` (BR-PUR-06 /
D-4: a CECO that purchases in the source NEVER gets the derived "cogs"
rows — zero double count; merge order BR-CO-10 extended with origin rank
{line:0, cogs:1, purchase:2}). Query economy NFR-BE8-2: +at most 2 SQL
queries per carryover request (purchasing-CECO set + purchases×terms),
+0 derived-purchase queries when the source has no purchases.

Transaction convention (T-05): write paths perform a SINGLE commit at the
end of the operation; on failure the caller rolls back. The planning upload
therefore uses ``create_scenario_budget`` (flush only, no commit) while the
legacy ``create_budget`` stays untouched for the legacy endpoints.
"""

import calendar
from typing import Any, Dict, List, Optional, Set, Tuple

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session, aliased

from app.models.budget import Budget as BudgetModel
from app.models.budget import BudgetLine as BudgetLineModel
from app.models.budget import CostCenter as CostCenterModel
from app.models.budget import LineCostRate as LineCostRateModel
from app.models.budget import LinePayableTerm as LinePayableTermModel
from app.models.budget.budgetLine import BehaviorTypeEnum, LineTypeEnum
from app.models.collection import Collection as CollectionModel
from app.schemas.budget import (
    BudgetCreate, BudgetLineCreate, PlanningCarryoverLine,
    PlanningLineCreate, PlanningLineUpdate,
)
from app.crud.budget.budgetLine import create_budget_lines_bulk


def planning_name_exists_in_year(
    db: Session, budget_year: int, budget_name: str
) -> bool:
    """BR-ING-04: uniqueness of (budget_year, budget_name) across the whole
    budgets table (bases and scenarios share the namespace)."""
    return db.query(BudgetModel.id_budget).filter(
        BudgetModel.budget_year == budget_year,
        BudgetModel.budget_name == budget_name,
    ).first() is not None


def create_scenario_budget(
    db: Session, budget: BudgetCreate
) -> BudgetModel:
    """Add + flush (NO commit) so the budget participates in the caller's
    single all-or-nothing transaction (BR-ING-01/BR-ING-02)."""
    db_budget = BudgetModel(**budget.model_dump())
    db.add(db_budget)
    db.flush()
    return db_budget


def get_planning_scenarios(
    db: Session, budget_year: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Listing for the planning dashboard (spec §5.4).

    Aggregation happens in SQL (NFR-5): one self LEFT JOIN resolves
    parent_budget_name and one grouped subquery over budget_lines provides
    lines_count / total_income / total_expense per budget. Base scenarios
    and alternatives are returned together (no is_scenario filter).

    Order: budget_year DESC, status (active -> draft -> closed), id_budget
    ASC.
    """
    line_agg = (
        db.query(
            BudgetLineModel.id_budget.label("id_budget"),
            func.count(BudgetLineModel.id_budget_line).label("lines_count"),
            func.sum(case(
                (BudgetLineModel.line_type == LineTypeEnum.INCOME,
                 BudgetLineModel.projected_amount),
                else_=0.0,
            )).label("total_income"),
            func.sum(case(
                (BudgetLineModel.line_type == LineTypeEnum.EXPENSE,
                 BudgetLineModel.projected_amount),
                else_=0.0,
            )).label("total_expense"),
        )
        .group_by(BudgetLineModel.id_budget)
        .subquery()
    )

    parent = aliased(BudgetModel)
    status_order = case(
        (BudgetModel.status == "active", 0),
        (BudgetModel.status == "draft", 1),
        (BudgetModel.status == "closed", 2),
        else_=3,
    )

    query = (
        db.query(
            BudgetModel.id_budget.label("id_budget"),
            BudgetModel.budget_name.label("budget_name"),
            BudgetModel.budget_year.label("budget_year"),
            BudgetModel.is_scenario.label("is_scenario"),
            parent.budget_name.label("parent_budget_name"),
            BudgetModel.status.label("status"),
            func.coalesce(line_agg.c.lines_count, 0).label("lines_count"),
            func.coalesce(line_agg.c.total_income, 0.0).label("total_income"),
            func.coalesce(line_agg.c.total_expense, 0.0).label("total_expense"),
            BudgetModel.created_at.label("created_at"),
            # BE-S6 §3.1: additive mirror of the new column for the
            # planning card chips (NFR-S6-BE-2 keeps every old key intact).
            BudgetModel.include_carryover.label("include_carryover"),
        )
        .outerjoin(parent, BudgetModel.parent_budget_id == parent.id_budget)
        .outerjoin(line_agg, line_agg.c.id_budget == BudgetModel.id_budget)
    )
    if budget_year is not None:
        query = query.filter(BudgetModel.budget_year == budget_year)

    rows = query.order_by(
        BudgetModel.budget_year.desc(),
        status_order,
        BudgetModel.id_budget.asc(),
    ).all()

    return [
        {
            "id_budget": row.id_budget,
            "budget_name": row.budget_name,
            "budget_year": row.budget_year,
            "is_scenario": bool(row.is_scenario),
            "parent_budget_name": row.parent_budget_name,
            "status": row.status,
            "lines_count": int(row.lines_count or 0),
            "total_income": float(row.total_income or 0.0),
            "total_expense": float(row.total_expense or 0.0),
            "created_at": row.created_at,
            "include_carryover": bool(row.include_carryover),
        }
        for row in rows
    ]


def clone_budget_with_modifier(
    db: Session,
    source_budget: BudgetModel,
    nuevo_nombre: str,
    modifier_pct: float,
) -> BudgetModel:
    """BR-CLN-01/02/03/04: linear copy of ALL budget_lines of the source
    into a new scenario budget in a single transaction.

    - projected_amount scaled by (1 + modifier_pct/100), native float, NO
      rounding (T-06 / BR-CLN-02).
    - variable_rate copied UNSCALED (BR-CLN-03: it is a rate; scaling it
      would corrupt the budgetEngine cash-flow).
    - The source is read as a snapshot and never mutated (BR-CLN-04).
    """
    factor = 1.0 + (modifier_pct / 100.0)

    new_budget = BudgetModel(
        budget_name=nuevo_nombre,
        budget_year=source_budget.budget_year,
        budget_period=source_budget.budget_period,
        id_department=source_budget.id_department,
        status="draft",
        is_scenario=True,
        parent_budget_id=source_budget.id_budget,
    )
    db.add(new_budget)
    db.flush()

    source_lines = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget == source_budget.id_budget
    ).all()

    lines_to_create = [
        BudgetLineCreate(
            id_budget=new_budget.id_budget,
            id_cost_center=line.id_cost_center,
            line_type=line.line_type,
            budget_date=line.budget_date,
            payment_date=line.payment_date,
            id_collection=line.id_collection,
            projected_amount=(line.projected_amount or 0.0) * factor,
            description=line.description,
            behavior_type=line.behavior_type,
            variable_rate=line.variable_rate,
        )
        for line in source_lines
    ]

    if lines_to_create:
        # Single commit for budget + cloned lines (T-05 / BR-CLN-01):
        # create_budget_lines_bulk flushes the pending new_budget too.
        create_budget_lines_bulk(db, lines_to_create)
    else:
        db.commit()

    db.refresh(new_budget)
    return new_budget


def update_budget_line_cell(
    db: Session,
    id_budget_line: int,
    projected_amount: float,
    description: Optional[str] = None,
) -> Optional[BudgetLineModel]:
    """BR-CEL-01: mutate ONLY projected_amount (and description when given).

    budget_date, payment_date, line_type, behavior_type, variable_rate,
    id_cost_center and id_budget are immutable through this path. No state
    lock: any draft/active/closed line can be edited, last-write-wins
    (BR-CEL-03 / ASM-7). Returns None when the line does not exist (404).
    """
    db_line = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()
    if db_line is None:
        return None

    db_line.projected_amount = projected_amount
    if description is not None:
        db_line.description = description
    db.commit()
    db.refresh(db_line)
    return db_line


# ──────────────────────────────────────────────────────────────
# BE-S4D-BUDGET-LINES (backend.02_13 §4): planning line manager
# ──────────────────────────────────────────────────────────────

# BE-S8-BUDGET-PURCHASES (backend.02_18 §5.1): LITERAL messages of the
# BR-PUR-02/03/04 guards, raised as 400 with a {"reason": ...} detail so
# the FE-S9 classifier can key off the structured shape (additive to the
# plain-string details of BR-LINE-04/07 which stay untouched).
# AMENDMENT A-01 (backend.02_18 §10.2): the shape guard no longer bans
# id_collection — a purchase MAY carry a season (temporada) like income —
# so the literal dropped the "no collection" clause. OLD literal (pre
# A-01): "purchase lines must be fixed with no collection and no
# variable rate".
PURCHASE_SHAPE_REASON = (
    "purchase lines must be fixed with no variable rate"
)
PURCHASE_PAYMENT_DATE_REASON = (
    "payment dates of a purchase derive from the line's payable terms"
)


def _is_purchase(line_type: Any) -> bool:
    """True for the BE-S8 third type. Enum-safe across the str-enum
    heritage (payload arrives as LineTypeEnum member, ORM column reads
    back as the member too; the literal guard keeps raw strings working).
    """
    return line_type == LineTypeEnum.PURCHASE


def _check_planning_line_cost_center(
    db: Session, id_cost_center: int
) -> None:
    """BR-LINE-02: cost-center existence for a unit mutation (404 with the
    exact detail of the §3.4 error matrix)."""
    found = db.query(CostCenterModel.id_cost_center).filter(
        CostCenterModel.id_cost_center == id_cost_center
    ).first()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cost center {id_cost_center} not found",
        )


def _check_planning_line_collection(db: Session, id_collection: int) -> None:
    """BR-LINE-02: collection existence (404, §3.4). Unit mutation => a
    plain 404 is enough (the missing_cost_centers payload of the upload
    is intentionally NOT reused here)."""
    found = db.query(CollectionModel.id_collection).filter(
        CollectionModel.id_collection == id_collection
    ).first()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {id_collection} not found",
        )


def _check_planning_line_budget_date_year(
    db: Session, id_budget: int, budget_date: date
) -> None:
    """BR-LINE-04/08: year(budget_date) must equal the PARENT scenario's
    budget_year (join via budgets). payment_date is never checked here: a
    payment landing in January of year+1 is legal (collection rules)."""
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget is None:
        # Defensive: only reachable through update_planning_line when the
        # parent vanished concurrently (FK makes it practically impossible).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Budget {id_budget} not found",
        )
    if budget_date.year != db_budget.budget_year:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"budget_date year {budget_date.year} does not match "
                f"scenario year {db_budget.budget_year}"
            ),
        )


def create_planning_line(
    db: Session, id_budget: int, payload: PlanningLineCreate
) -> BudgetLineModel:
    """POST /budget/planning/{id_budget}/line (backend.02_13 §3.1).

    Validations (all inside this layer, raising HTTPException with the §3.4
    error matrix detail):
    - BR-LINE-01: id_budget must exist -> 404 "Budget {id} not found".
    - BR-LINE-02: id_cost_center / id_collection existence -> 404.
    - BR-LINE-03: variable lines get projected_amount FORCED to 0 even if
      the body sent another value (AC-UP-1 invariant: the amount is derived
      from the rate; the FE does not even send it).
    - BR-LINE-04: budget_date year == budget_year -> 400 otherwise.
    - BR-LINE-05: no status lock (draft/active/closed all mutable).
    No uniqueness restriction (D-4: CECO+date+type may repeat, mirroring
    the multi-line payment-rule expansion of the ingestion).
    Single commit (T-05); returns the full persisted row (NFR-L-2).

    BE-S7-COGS-PAYFLOW §2 rollback: the BE-S5 §6/§7 payable-terms
    expansion of eligible fixed-expense payloads (tuple return with
    siblings, N installment rows in one transaction) is RETIRED — this
    function again persists EXACTLY ONE row with the payload's own
    payment_date and returns ONLY it, byte-identical to BE-S4D
    (``line_payable_terms`` now describes how the supplier of the Line's
    COGS gets paid; it is consumed by the carryover derivation below and
    by the FE-S7 live view, never materialized here).

    BE-S8-BUDGET-PURCHASES §5.1-1 (BR-PUR-02/03), AMENDED by A-01 §10.2:
    a ``line_type='purchase'`` payload must be fixed with no variable
    rate (400 ``{"reason": ...}`` raised BEFORE the collection FK check
    so an irrelevant-but-present id_collection never masks the shape
    error); ``id_collection`` IS NOW VALID on a purchase — the season
    (temporada) metadata with income parity — and simply falls through
    to the existing existence validation (404 "Collection {id} not
    found" when unknown); a sent ``payment_date`` is FORCED to NULL
    in silence (BR-PUR-03, the supplier installments of a purchase are
    read-derived, NFR-BE8-1). All other validations (budget 404, CECO
    404, year 400, single commit) stand.
    """
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Budget {id_budget} not found",
        )
    _check_planning_line_cost_center(db, payload.id_cost_center)
    if _is_purchase(payload.line_type):
        # BR-PUR-02 (A-01 §10.2): shape guard covers behavior/rate ONLY —
        # id_collection is legal season metadata (404-checked below).
        if (payload.behavior_type != BehaviorTypeEnum.FIXED
                or payload.variable_rate is not None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"reason": PURCHASE_SHAPE_REASON},
            )
    if payload.id_collection is not None:
        _check_planning_line_collection(db, payload.id_collection)
    if payload.budget_date.year != db_budget.budget_year:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"budget_date year {payload.budget_date.year} does not match "
                f"scenario year {db_budget.budget_year}"
            ),
        )

    data = payload.model_dump()
    if payload.behavior_type != BehaviorTypeEnum.FIXED:
        # BR-LINE-03: server-side invariant over whatever the body sent.
        data["projected_amount"] = 0.0
    if _is_purchase(payload.line_type):
        # BR-PUR-03: silent NULL — installments derive at read time from
        # line_payable_terms anchored on budget_date (the import date).
        data["payment_date"] = None

    db_line = BudgetLineModel(id_budget=id_budget, **data)
    db.add(db_line)
    db.commit()
    db.refresh(db_line)
    return db_line


def update_planning_line(
    db: Session, id_budget_line: int, payload: PlanningLineUpdate
) -> Optional[BudgetLineModel]:
    """PUT /budget/planning/line/{id_budget_line} (backend.02_13 §3.2).

    Partial contract (like LineCostRateUpdate): only fields present in the
    body with a non-null value are applied; omitted = keep.

    - Line missing -> None (404 at the API layer, EXACT convention of
      update_budget_line_cell / planning_update_cell).
    - BR-LINE-06: line_type/behavior_type are absent from the schema and
      silently ignored if sent (extra=ignore); they stay immutable here.
    - BR-LINE-07: projected_amount SENT on a variable line -> 400;
      variable_rate SENT on a fixed line -> 400 (detected via
      model_fields_set so "present but null" also counts as sent).
    - BR-LINE-02/08: provided FKs and the new budget_date year are checked
      with the §3.4 details (404 / 400).
    - BR-LINE-05: no status lock.

    BE-S8-BUDGET-PURCHASES §5.1-2 (BR-PUR-04), AMENDED by A-01 §10.2: on
    a PERSISTED purchase row a SENT payment_date -> 400
    {"reason": PURCHASE_PAYMENT_DATE_REASON} (the installments derive
    from the Line's payable terms — writing a date would silently
    desynchronize them) and a SENT variable_rate -> 400 with the
    BR-PUR-02 shape message. A SENT id_collection is now VALID (season
    metadata parity with income): it flows to the generic existence
    check below -> 404 "Collection {id} not found" when unknown. "Sent"
    is detected via model_fields_set (present-but-null counts, BR-LINE-07
    precedent). budget_date stays editable with the year check (fixing an
    import date), projected_amount/description/cost center with the
    generic fixed-line rules. line_type remains immutable (BR-LINE-06:
    absent from PlanningLineUpdate, extra=ignore — verified at the schema
    level, not rechecked here). Guards run BEFORE the generic behavior
    guards so a purchase never answers the "fixed lines..." wording.
    Single commit (T-05); returns the full persisted row (NFR-L-2).
    """
    db_line = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()
    if db_line is None:
        return None

    sent = payload.model_fields_set
    if _is_purchase(db_line.line_type):
        # BR-PUR-04: payment_date first (spec §5.1-2 order), then shape.
        # id_collection deliberately NOT banned here (A-01 §10.2): the
        # season is legal on purchases and 404-checked generically.
        if "payment_date" in sent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"reason": PURCHASE_PAYMENT_DATE_REASON},
            )
        if "variable_rate" in sent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"reason": PURCHASE_SHAPE_REASON},
            )
    is_variable = db_line.behavior_type != BehaviorTypeEnum.FIXED
    if is_variable and "projected_amount" in sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "variable lines derive their amount from the rate; "
                "edit variable_rate instead"
            ),
        )
    if not is_variable and "variable_rate" in sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "fixed lines do not carry a variable rate; "
                "edit projected_amount instead"
            ),
        )

    merged = payload.model_dump(exclude_none=True)
    if "id_cost_center" in merged:
        _check_planning_line_cost_center(db, merged["id_cost_center"])
    if "id_collection" in merged:
        _check_planning_line_collection(db, merged["id_collection"])
    if "budget_date" in merged:
        _check_planning_line_budget_date_year(
            db, db_line.id_budget, merged["budget_date"]
        )

    for key, value in merged.items():
        setattr(db_line, key, value)
    db.commit()
    db.refresh(db_line)
    return db_line


def delete_planning_line(
    db: Session, id_budget_line: int
) -> Optional[BudgetLineModel]:
    """DELETE /budget/planning/line/{id_budget_line} (backend.02_13 §3.3).

    Physical delete (D-2: no soft flag / trash in v1). No cascades: no
    other table references budget_lines (verified in §2). No status lock
    (BR-LINE-05). Returns the deleted row, or None when missing -> 404 at
    the API layer (same convention as update_planning_line / cell).
    """
    db_line = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget_line == id_budget_line
    ).first()
    if db_line is None:
        return None
    db.delete(db_line)
    db.commit()
    return db_line


def budget_year_active_exists(
    db: Session, budget_year: int, exclude_id: Optional[int] = None
) -> bool:
    """True when some other budget of ``budget_year`` already carries
    status='active' (invariant helper for BR-TGT-01)."""
    query = db.query(BudgetModel.id_budget).filter(
        BudgetModel.budget_year == budget_year,
        BudgetModel.status == "active",
    )
    if exclude_id is not None:
        query = query.filter(BudgetModel.id_budget != exclude_id)
    return query.first() is not None


def set_active_target(
    db: Session, id_budget: int
) -> Optional[Dict[str, Any]]:
    """PUT /budget/planning/{id_budget}/set-target (BR-TGT-01/02).

    Single transaction: activate the chosen budget and close every OTHER
    active budget of the SAME budget_year (max one active per year).
    Idempotent: setting the budget that is already the target returns 200
    with no changes (BR-TGT-02). Returns None when the budget does not
    exist (caller raises 404).
    """
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget is None:
        return None

    others_active = budget_year_active_exists(
        db, db_budget.budget_year, exclude_id=id_budget
    )
    if db_budget.status == "active" and not others_active:
        # BR-TGT-02: already the target -> 200 without changes.
        return {
            "id_budget": db_budget.id_budget,
            "budget_year": db_budget.budget_year,
            "demoted_budget_id": None,
        }

    demoted = (
        db.query(BudgetModel)
        .filter(
            BudgetModel.budget_year == db_budget.budget_year,
            BudgetModel.status == "active",
            BudgetModel.id_budget != id_budget,
        )
        .order_by(BudgetModel.id_budget.asc())
        .all()
    )
    # Contract exposes a single demoted id; if historical dirty data had
    # more than one active row, ALL of them are demoted and the lowest
    # id_budget is reported (mirrors the budgetEngine Q0 tie-break).
    demoted_budget_id = demoted[0].id_budget if demoted else None
    for other in demoted:
        other.status = "closed"

    db_budget.status = "active"
    db.commit()

    return {
        "id_budget": db_budget.id_budget,
        "budget_year": db_budget.budget_year,
        "demoted_budget_id": demoted_budget_id,
    }


def get_budget_with_parent_name(
    db: Session, id_budget: int
) -> Optional[Tuple[BudgetModel, Optional[str]]]:
    """Budget row + parent budget_name (self LEFT JOIN) for §5.5 detail.

    Returns None when the budget does not exist (caller raises 404).
    """
    parent = aliased(BudgetModel)
    row = (
        db.query(BudgetModel, parent.budget_name.label("parent_budget_name"))
        .outerjoin(parent, BudgetModel.parent_budget_id == parent.id_budget)
        .filter(BudgetModel.id_budget == id_budget)
        .first()
    )
    if row is None:
        return None
    return row[0], row[1]


# ──────────────────────────────────────────────────────────────
# BE-S6-CARRYOVER (backend.02_16 §4): prior-year balance carry-in
#
# Read-only derivation helpers: the pair below costs EXACTLY 2 SQL round
# trips per enabled GET (NFR-S6-BE-1: source + its lines, both fully
# filtered/ordered in SQL, never in Python) and 0 extra queries when the
# flag is OFF (BR-CO-01 short-circuit lives in the API layer, after the
# mandatory scenario read that raises the 404 first). BR-CO-04/05: no
# writes, no snapshots, no chaining — every request recomputes from the
# live N−1 scenario.
# ──────────────────────────────────────────────────────────────

def get_carryover_source_budget(
    db: Session, budget_year_prev: int, exclude_id: int
) -> Optional[BudgetModel]:
    """BR-CO-02: deterministic pick of the N−1 scenario to carry from.

    Candidate scope mirrors GET /budget/planning/ EXACTLY (verified against
    get_planning_scenarios: the listing has no is_scenario/status
    discriminator — every row of `budgets` is a scenario), narrowed to
    budget_year == N-1 and self-excluded. Winner ordering:

      1. status priority ACTIVE > CLOSED > DRAFT (the stored casing is the
         lowercase strings used by set_active_target/get_planning_scenarios
         — 'active'/'closed'/'draft'; any other/NULL status ranks last);
      2. tie inside a status: updated_at DESC (NULLS LAST defensively:
         budgets.updated_at is server_default now(), so in practice never
         NULL — the column the spec names exists as-is, no adaptation);
      3. final tie-break id_budget DESC (deterministic).

    Returns None when there is no candidate (caller answers
    unavailable_reason="no_source").
    """
    status_priority = case(
        (BudgetModel.status == "active", 0),
        (BudgetModel.status == "closed", 1),
        (BudgetModel.status == "draft", 2),
        else_=3,
    )
    return (
        db.query(BudgetModel)
        .filter(
            BudgetModel.budget_year == budget_year_prev,
            BudgetModel.id_budget != exclude_id,
        )
        .order_by(
            status_priority.asc(),
            BudgetModel.updated_at.desc().nullslast(),
            BudgetModel.id_budget.desc(),
        )
        .first()
    )


def get_carryover_lines(
    db: Session, id_budget_source: int, budget_year_target: int
) -> List[BudgetLineModel]:
    """BR-CO-03: pending balances of the SOURCE scenario that settle inside
    the target year N.

    Filter (fully in SQL, NFR-S6-BE-1): behavior_type == FIXED — compared
    through the ORM enum member because the legacy `character varying(20)`
    column stores the SQLAlchemy NAME representation ('FIXED', verified
    against the dev data; a raw 'fixed' string would match nothing) — and
    year of the EFFECTIVE date coalesce(payment_date, budget_date) == N.
    A NULL payment_date therefore falls back to budget_date (year N-1 of
    the source) and is excluded naturally. Both income AND expense rows are
    returned (collections and payments carry over).

    BE-S8 §3.4-4 (BR-CO-12): ``line_type != PURCHASE`` is excluded
    EXPLICITLY. Purchase rows are structurally un-selectable here (their
    payment_date is always NULL and their budget_date lives in N−1), but
    the guard removes that reliance on the invariant: a dirty-data
    purchase anchored in N never materializes as an origin "line" row —
    it only ever flows through the §4 installment derivation.

    Stable order (§5.1): effective date ASC, then id_budget_line ASC.
    """
    effective_date = func.coalesce(
        BudgetLineModel.payment_date, BudgetLineModel.budget_date
    )
    return (
        db.query(BudgetLineModel)
        .filter(
            BudgetLineModel.id_budget == id_budget_source,
            BudgetLineModel.behavior_type == BehaviorTypeEnum.FIXED,
            BudgetLineModel.line_type != LineTypeEnum.PURCHASE,
            func.extract("year", effective_date) == budget_year_target,
        )
        .order_by(effective_date.asc(), BudgetLineModel.id_budget_line.asc())
        .all()
    )


# ──────────────────────────────────────────────────────────────
# BE-S7-COGS-PAYFLOW (backend.02_17 §4): derived COGS carry-in
#
# BR-CO-09..11: on top of the material rows of BE-S6 the carryover payload
# ALSO answers COGS supplier-payment installments DERIVED from the FIXED
# INCOME lines of the source (year N−1). Pure per-request read-derivation
# (coherent with BR-CO-04: zero cache, zero writes — the cost is NEVER
# materialized in budget_lines, D-S7-2). The cost resolution mirrors
# budgetEngine.get_pnl's cost pool EXACTLY (backend.02_17 §3: active
# rates ordered by id_line_cost_rate DESC, month-end of the income row's
# budget_date within [date_from, date_to], cogs_pct scale 0–100, id_line
# NULL = global fallback for every line). Query economy (BR-CO-11): income
# rows + rate pool + terms = a CONSTANT few queries, each result cached
# per request (terms fetched once for ALL distinct Lines of the source).
# ──────────────────────────────────────────────────────────────

COGS_CARRYOVER_DESCRIPTION = "Costo de venta (arrastre)"


def _month_end(day: date) -> date:
    """Last calendar day of ``day``'s month — the rate-validity anchor used
    by the carryover derivation (backend.02_17 §3/§4: month-end ∈
    [date_from, date_to], mirroring get_pnl's period-end semantics)."""
    return date(
        day.year, day.month, calendar.monthrange(day.year, day.month)[1]
    )


def _cogs_pct_pool_for_month(
    active_rates_desc: List[Any], month_end: date
) -> Tuple[Dict[int, float], Optional[float]]:
    """(pct_by_line, global_fallback) of the ACTIVE rates in force at
    ``month_end`` — the Python mirror of get_pnl Q6
    (app/services/budgetEngine.py:480-492) evaluated per month-end instead
    of a single period end: same DESC pool scan, first hit wins per Line
    (``setdefault``) and the FIRST NULL-id rate is the global fallback.
    ``active_rates_desc`` must already be ordered by
    ``id_line_cost_rate DESC`` and filtered to ``is_active`` (the batch
    fetch of BR-CO-11); only the date window is applied here."""
    pct_by_line: Dict[int, float] = {}
    fallback_pct: Optional[float] = None
    for rate in active_rates_desc:
        if not (rate.date_from <= month_end <= rate.date_to):
            continue
        if rate.id_line is None:
            fallback_pct = (
                float(rate.cogs_pct) if fallback_pct is None else fallback_pct
            )
        else:
            pct_by_line.setdefault(rate.id_line, float(rate.cogs_pct))
    return pct_by_line, fallback_pct


def get_carryover_cogs_lines(
    db: Session,
    id_budget_source: int,
    budget_year_source: int,
    budget_year_target: int,
    purchasing_cc_ids: Optional[Set[int]] = None,
) -> List[Dict[str, Any]]:
    """BR-CO-09: COGS payment installments derived from the FIXED INCOME
    lines of the source scenario whose ``budget_date`` falls in the source
    year N−1.

    BE-S8-BUDGET-PURCHASES §5.1-4 (BR-PUR-06 / single-source rule D-4):
    ``purchasing_cc_ids`` — the CECOs of the SOURCE that own at least one
    purchase row — are EXCLUDED from the income scan (SQL ``NOT IN``,
    zero extra queries). A purchasing CECO's supplier payment derives
    from its purchases (``get_carryover_purchase_lines``), never from
    both sources: zero double count. Empty/None keeps the pre-BE-S8
    behavior byte-identical (NFR-BE8-3).

    Per eligible income row (D-S7-5 anchor = its ``budget_date``):
    1. resolve ``pct`` = cogs of the CECO's Line at month-end(budget_date)
       through the get_pnl-mirror pool (line rate first, NULL-id global
       fallback second; same 0–100 scale). No rate resolved -> the row is
       SILENTLY SKIPPED, zero derived rows (AC-S7-BE-6; unlike get_pnl we
       add no warning channel — this is a pure read projection).
    2. cost = amount × pct / 100 (native float, no intermediate rounding —
       same convention as the income collection expansion and the P&L
       contribution maths).
    3. terms = ``line_payable_terms`` of that id_line in the D-7 order
       (payment_days asc, id asc): WITH terms -> one derived row per term,
       payment_date = anchor + payment_days, amount = cost × payment_pct
       (pct applied as-is, no single-0 special case and no 100 %-sum
       validation here — the derivation re-semantized the catalog, so
       superseded BR-TERM-03/05 do not apply). WITHOUT terms (or CECO
       without id_line) -> ONE row at 100 % with payment_date = the anchor
       itself (D-S7-4: the cost still has to be paid).
    4. keep ONLY rows whose year(payment_date) == budget_year_target
       (BR-CO-09; offsets landing outside N — either direction — simply
       do not carry over).

    Returns dicts shaped as ``PlanningCarryoverLine`` with
    ``origin="cogs"``, ``id_budget_line=None``, ``line_type="expense"``
    and description ``COGS_CARRYOVER_DESCRIPTION`` (BR-CO-10). Generation
    order is deterministic (income id_budget_line ASC, then terms D-7
    order); the caller owns the final BR-CO-10 merge sort.

    Queries (BR-CO-11): income rows (1) + rate pool (1) + terms of ALL
    distinct id_lines (1 batched ``IN`` query) = exactly 2 EXTRA queries
    on top of the income fetch, independent of row counts; the
    per-month-end pool is memoed in-request."""
    income_query = (
        db.query(BudgetLineModel, CostCenterModel.id_line)
        .join(
            CostCenterModel,
            BudgetLineModel.id_cost_center
            == CostCenterModel.id_cost_center,
        )
        .filter(
            BudgetLineModel.id_budget == id_budget_source,
            BudgetLineModel.line_type == LineTypeEnum.INCOME,
            BudgetLineModel.behavior_type == BehaviorTypeEnum.FIXED,
            func.extract("year", BudgetLineModel.budget_date)
            == budget_year_source,
        )
    )
    if purchasing_cc_ids:
        # BR-PUR-06 / D-4: income of a purchasing CECO never derives cogs
        # (its supplier payment comes from get_carryover_purchase_lines).
        # sorted() keeps the IN list deterministic for SQL logging/tests.
        income_query = income_query.filter(
            BudgetLineModel.id_cost_center.notin_(
                sorted(int(cc_id) for cc_id in purchasing_cc_ids)
            )
        )
    income_rows = income_query.order_by(
        BudgetLineModel.id_budget_line.asc()
    ).all()
    if not income_rows:
        return []

    active_rates = (
        db.query(LineCostRateModel)
        .filter(LineCostRateModel.is_active.is_(True))
        .order_by(LineCostRateModel.id_line_cost_rate.desc())
        .all()
    )

    id_lines = sorted({
        id_line for _budget_line, id_line in income_rows
        if id_line is not None
    })
    terms_by_line: Dict[int, List[LinePayableTermModel]] = {
        id_line: [] for id_line in id_lines
    }
    if id_lines:
        for term in (
            db.query(LinePayableTermModel)
            .filter(LinePayableTermModel.id_line.in_(id_lines))
            .order_by(
                LinePayableTermModel.id_line,
                LinePayableTermModel.payment_days,
                LinePayableTermModel.id_line_payable_term,
            )
            .all()
        ):
            terms_by_line[term.id_line].append(term)

    pool_cache: Dict[date, Tuple[Dict[int, float], Optional[float]]] = {}
    derived: List[Dict[str, Any]] = []
    for budget_line, id_line in income_rows:
        month_end = _month_end(budget_line.budget_date)
        if month_end not in pool_cache:
            pool_cache[month_end] = _cogs_pct_pool_for_month(
                active_rates, month_end
            )
        pct_by_line, fallback_pct = pool_cache[month_end]

        # get_pnl D-2/BR-7 chain (budgetEngine.py:505-513): line rate ->
        # global fallback -> (here) silent exclusion.
        pct = pct_by_line.get(id_line) if id_line is not None else None
        if pct is None:
            pct = fallback_pct
        if pct is None:
            continue

        cost = float(budget_line.projected_amount or 0.0) * pct / 100.0
        terms = terms_by_line.get(id_line) if id_line is not None else None
        if terms:
            candidates = [
                (
                    budget_line.budget_date
                    + timedelta(days=term.payment_days),
                    cost * float(term.payment_pct),
                )
                for term in terms
            ]
        else:
            # D-S7-4: no terms (Line without terms, or CECO without
            # id_line) -> the full cost paid on the anchor day itself.
            candidates = [(budget_line.budget_date, cost)]

        for payment_date, amount in candidates:
            if payment_date.year != budget_year_target:
                continue                        # BR-CO-09 year filter
            derived.append({
                "id_budget_line": None,
                "id_cost_center": budget_line.id_cost_center,
                "line_type": "expense",
                "budget_date": budget_line.budget_date,
                "payment_date": payment_date,
                "projected_amount": amount,
                "description": COGS_CARRYOVER_DESCRIPTION,
                "origin": "cogs",
            })
    return derived


# ──────────────────────────────────────────────────────────────
# BE-S8-BUDGET-PURCHASES (backend.02_18 §4/§5.1): purchase carry-in
#
# The supplier installments of the source's PURCHASE rows are derived
# exactly like the COGS ones above (same D-7 term order, same D-S7-4
# no-terms fallback, same "apply the pcts as-is" rule and raw-float math)
# — only the base differs: the merchandise value projected_amount itself
# instead of income × cogs_pct (there is no rate lookup and no per-month
# pool: the purchase IS the cost). Query economy (NFR-BE8-2): the pair
# below adds AT MOST 2 SQL round trips per carryover request — 1 for the
# purchasing-CECO set (which also feeds the D-4 exclusion above) and 1
# for the purchases×terms join — regardless of row counts. A source
# without purchases pays only the set query (the join short-circuits on
# the empty set in build_carryover_payload_lines).
# ──────────────────────────────────────────────────────────────

PURCHASE_CARRYOVER_DESCRIPTION = "Pago a proveedor (arrastre)"


def get_purchasing_cc_ids(db: Session, id_budget_source: int) -> Set[int]:
    """Single-source rule D-4 (BR-PUR-06): cost-center ids of the SOURCE
    that own at least one purchase row — such a CECO's supplier payment
    derives from its purchases, NEVER from income × cogs_pct (and vice
    versa for non-purchasing CECOs, which keep the FE-S7 derivation).

    1 query: SELECT DISTINCT id_cost_center ... line_type = PURCHASE
    (spec §5.1-4). Feeds both the cogs-scan NOT IN exclusion and the
    purchase-derivation short-circuit below."""
    return {
        id_cost_center
        for (id_cost_center,) in db.query(
            BudgetLineModel.id_cost_center
        ).filter(
            BudgetLineModel.id_budget == id_budget_source,
            BudgetLineModel.line_type == LineTypeEnum.PURCHASE,
        ).distinct().all()
    }


def get_carryover_purchase_lines(
    db: Session, id_budget_source: int, budget_year_target: int
) -> List[Dict[str, Any]]:
    """BR-PUR-05: supplier-payment installments derived from the PURCHASE
    rows of the source scenario (spec §4), kept when
    year(installment_date) == ``budget_year_target`` (BR-CO-09 mirror —
    the import itself belongs to N−1, a January/February installment is
    precisely the carry-in).

    Per purchase row (anchor = ``budget_date`` = import date; the row's
    own ``payment_date`` is NULL by BR-PUR-01/03 and never consulted):
    terms = ``line_payable_terms`` of the CECO's id_line in the D-7 order
    (payment_days asc, id asc): WITH terms -> one installment per term,
    date = anchor + payment_days, amount = projected_amount ×
    payment_pct (pct applied as-is, NOT normalized — even when the pcts
    do not sum to 1; zero cogs_pct: the merchandise value is the cost).
    WITHOUT terms (Line without terms, or CECO without id_line) -> ONE
    installment at 100 % on the import date (D-S7-4). Raw float, zero
    intermediate rounding (repo convention).

    ONE query (NFR-BE8-2): purchase rows LEFT JOIN cost_centers LEFT
    JOIN line_payable_terms, fully ordered in SQL
    (id_budget_line ASC, payment_days ASC, id_line_payable_term ASC —
    PG puts the NULL term of a no-terms line FIRST inside its group, and
    rows are re-grouped in Python keeping that generation order, so the
    output is deterministic per NFR-BE8-4). Terms-less purchases with
    multiple rows would duplicate the line tuple; the grouping collapses
    them.

    Returns ``PlanningCarryoverLine``-shaped dicts with
    ``origin="purchase"``, ``line_type="expense"``, ``id_budget_line=None``,
    ``budget_date`` = import date, ``payment_date`` = installment date and
    description ``PURCHASE_CARRYOVER_DESCRIPTION`` (BR-PUR-05)."""
    rows = (
        db.query(
            BudgetLineModel,
            CostCenterModel.id_line,
            LinePayableTermModel,
        )
        .outerjoin(
            CostCenterModel,
            BudgetLineModel.id_cost_center
            == CostCenterModel.id_cost_center,
        )
        .outerjoin(
            LinePayableTermModel,
            LinePayableTermModel.id_line == CostCenterModel.id_line,
        )
        .filter(
            BudgetLineModel.id_budget == id_budget_source,
            BudgetLineModel.line_type == LineTypeEnum.PURCHASE,
        )
        .order_by(
            BudgetLineModel.id_budget_line.asc(),
            LinePayableTermModel.payment_days.asc(),
            LinePayableTermModel.id_line_payable_term.asc(),
        )
        .all()
    )

    # Regroup the join fan-out preserving the SQL order: first appearance
    # fixes the line order, terms stay in D-7 order inside each bucket.
    by_line: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for budget_line, id_line, term in rows:
        key = budget_line.id_budget_line
        if key not in by_line:
            by_line[key] = {
                "line": budget_line,
                "id_line": id_line,
                "terms": [],
            }
            order.append(key)
        if term is not None:
            by_line[key]["terms"].append(term)

    derived: List[Dict[str, Any]] = []
    for key in order:
        entry = by_line[key]
        budget_line = entry["line"]
        amount = float(budget_line.projected_amount or 0.0)
        terms = entry["terms"] if entry["id_line"] is not None else []
        if terms:
            candidates = [
                (
                    budget_line.budget_date
                    + timedelta(days=term.payment_days),
                    amount * float(term.payment_pct),
                )
                for term in terms
            ]
        else:
            # D-S7-4 mirror: no terms (or CECO without id_line) -> the
            # full merchandise value paid on the import date itself.
            candidates = [(budget_line.budget_date, amount)]

        for payment_date, installment in candidates:
            if payment_date.year != budget_year_target:
                continue                        # BR-CO-09 year filter
            derived.append({
                "id_budget_line": None,
                "id_cost_center": budget_line.id_cost_center,
                "line_type": "expense",
                "budget_date": budget_line.budget_date,
                "payment_date": payment_date,
                "projected_amount": installment,
                "description": PURCHASE_CARRYOVER_DESCRIPTION,
                "origin": "purchase",
            })
    return derived


def _carryover_order_key(
    row: PlanningCarryoverLine,
) -> Tuple[date, int, int]:
    """BR-CO-10 sort key (BE-S8 §5.1-4 extended): effective date
    coalesce(payment_date, budget_date) ASC, then origin rank
    ("line" < "cogs" < "purchase" on ties), then the id null-safe
    (derived rows share 0 and keep their deterministic generation order —
    Python's sort is stable)."""
    origin_rank = {
        "line": 0,
        "cogs": 1,
        "purchase": 2,
    }
    return (
        row.payment_date or row.budget_date,
        origin_rank.get(row.origin, 0),
        row.id_budget_line if row.id_budget_line is not None else 0,
    )


def build_carryover_payload_lines(
    db: Session,
    id_budget_source: int,
    budget_year_source: int,
    budget_year_target: int,
) -> List[PlanningCarryoverLine]:
    """Full GET-carryover payload rows (backend.02_16 §5.1 material +
    backend.02_17 §4 derived + backend.02_18 §5.1 purchase derived) in the
    BR-CO-10 order extended with origin rank {line:0, cogs:1, purchase:2}.
    Material ORM rows validate with the schema default ``origin="line"``
    (they carry no such attribute). Called ONLY when the include_carryover
    flag is ON — the BR-CO-01 short-circuit lives in the API layer, so the
    disabled path keeps paying zero queries (AC-S7-BE-8).

    BE-S8 single-source switch (BR-PUR-06 / D-4): the purchasing-CECO set
    of the SOURCE is computed ONCE (1 DISTINCT query) and fed BOTH to the
    income-scan exclusion of get_carryover_cogs_lines (a purchasing CECO
    never gets cogs-derived rows) AND as the gate for
    get_carryover_purchase_lines (1 purchases×terms query, skipped when
    the set is empty). A source without purchases therefore pays exactly
    +1 cheap DISTINCT query over BE-S7 and produces byte-identical
    payloads (NFR-BE8-3); with purchases the budget is +2 queries total
    regardless of row counts (NFR-BE8-2)."""
    material = [
        PlanningCarryoverLine.model_validate(row)
        for row in get_carryover_lines(
            db, id_budget_source, budget_year_target
        )
    ]
    purchasing_cc_ids = get_purchasing_cc_ids(db, id_budget_source)
    derived_rows = get_carryover_cogs_lines(
        db, id_budget_source, budget_year_source, budget_year_target,
        purchasing_cc_ids=purchasing_cc_ids,
    )
    if purchasing_cc_ids:
        # BR-PUR-05: only sources with >=1 purchasing CECO pay the join.
        derived_rows = derived_rows + get_carryover_purchase_lines(
            db, id_budget_source, budget_year_target,
        )
    derived = [PlanningCarryoverLine(**data) for data in derived_rows]
    merged = material + derived
    merged.sort(key=_carryover_order_key)
    return merged


def set_planning_carryover_flag(
    db: Session, id_budget: int, include_carryover: bool
) -> Optional[BudgetModel]:
    """PUT /budget/planning/{id_budget}/carryover (BR-CO-08).

    Mutates ONLY include_carryover — never validates the scenario year nor
    the existence of a source (flag ON without source is legal state).
    Idempotent: re-setting the stored value emits no UPDATE at all (the ORM
    only flushes net changes) and still returns the refreshed row. Missing
    budget -> None (the API layer raises the 404 with the verbatim
    "Budget {id} not found" detail of create_planning_line / BR-CO-07 —
    NOT Exceptions.register_not_found, whose wording differs).
    """
    db_budget = db.query(BudgetModel).filter(
        BudgetModel.id_budget == id_budget
    ).first()
    if db_budget is None:
        return None

    db_budget.include_carryover = include_carryover
    db.commit()
    db.refresh(db_budget)
    return db_budget
