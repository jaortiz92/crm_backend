"""
Budget Planning CRUD Operations (BE-S4-BUDGET-PLANNING)

Legacy ``db.query(Model).filter(...)`` style (T-03). The functions here back
the /budget/planning endpoints (spec backend.02_12 §5): SQL-level scenario
listing, clone with percentage modifier, single-cell edit, and the
"one active target per year" transaction (BR-TGT-01).

Transaction convention (T-05): write paths perform a SINGLE commit at the
end of the operation; on failure the caller rolls back. The planning upload
therefore uses ``create_scenario_budget`` (flush only, no commit) while the
legacy ``create_budget`` stays untouched for the legacy endpoints.
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session, aliased

from app.models.budget import Budget as BudgetModel
from app.models.budget import BudgetLine as BudgetLineModel
from app.models.budget.budgetLine import LineTypeEnum
from app.schemas.budget import BudgetCreate, BudgetLineCreate
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
