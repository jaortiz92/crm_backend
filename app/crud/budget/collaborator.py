"""
Collaborator CRUD Operations (BE-S11-COLLABORATORS, backend.02_21)

Legacy ``db.query(Model).filter(...)`` style with ``db: Session`` first
(T-03). NO commit here except where noted: the import/create/terminate/
recalculate flows span master + plans + motor + budget_lines in ONE
transaction, so by T-05 the CALLER (API layer) owns the single
``db.commit()`` — these functions only ``add``/``flush``/mutate (the
``create_scenario_budget`` add+flush precedent from crud/budget/
planning.py).

Salary plans are historized: a raise CLOSES the open plan
(valid_to = valid_from - 1) and appends a new vigencia — closed history
is never edited (BR-02/BR-COLLAB-02, NFR-03 "nunca DELETE de
históricos"). The motor-owned replacement helpers below deliberately
touch ONLY ``source_engine LIKE 'collaborator_%'`` rows (R-13 / BR-09:
manual lines, other templates and the REAL side coexist untouched —
invariante verificable).
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.budget import (
    Budget as BudgetModel,
    Collaborator,
    CollaboratorSalaryPlan,
    CollaboratorProvisionAccrual,
    CostComponent,
    LaborArlRate,
    LaborCostParameter,
)
from app.models.budget.budgetLine import BudgetLine as BudgetLineModel

# Engine row ownership (D-S11-5 / R-13): pattern literal shared with the
# motor; LIKE 'collaborator_%' is the ONLY predicate that may ever delete
# materialized payroll lines.
ENGINE_SOURCE_PATTERN = "collaborator_%"
SOURCE_ENGINE_COST = "collaborator_cost"
SOURCE_ENGINE_LIQUIDATION = "collaborator_liquidation"


# ──────────────────────────────────────────────────
# Master
# ──────────────────────────────────────────────────

def get_collaborator_by_id(
    db: Session, id_collaborator: int
) -> Optional[Collaborator]:
    """One collaborator by PK (None -> 404 at the API layer)."""
    return db.query(Collaborator).filter(
        Collaborator.id_collaborator == id_collaborator
    ).first()


def get_collaborator_by_doc_value(
    db: Session, doc_value: str
) -> Optional[Collaborator]:
    """Natural upsert key of the payroll template (R-07)."""
    return db.query(Collaborator).filter(
        Collaborator.doc_value == doc_value
    ).first()


def query_collaborators(
    db: Session,
    q: Optional[str] = None,
    id_cost_center: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> Tuple[int, List[Collaborator]]:
    """GET /budget/collaborator (§9): {total, items[]} with optional
    text search (name/doc), cost-center and status filters + pagination.
    Returns (total, page_items). Order: full_name, id."""
    query = db.query(Collaborator)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Collaborator.full_name.ilike(like),
            Collaborator.doc_value.ilike(like),
        ))
    if id_cost_center is not None:
        query = query.filter(Collaborator.id_cost_center == id_cost_center)
    if status:
        query = query.filter(Collaborator.status == status)

    total = query.count()
    items = (
        query.order_by(Collaborator.full_name, Collaborator.id_collaborator)
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    return total, items


def create_collaborator(
    db: Session, fields: Dict[str, Any]
) -> Collaborator:
    """Add the master row (flush only — the caller commits, T-05)."""
    db_collaborator = Collaborator(**fields)
    db.add(db_collaborator)
    db.flush()
    return db_collaborator


def update_collaborator_master(
    db: Session,
    db_collaborator: Collaborator,
    fields: Dict[str, Any],
) -> Collaborator:
    """PUT of the master fields ONLY (salary never — §9). Applied
    in-place; the caller commits (T-05)."""
    for key, value in fields.items():
        setattr(db_collaborator, key, value)
    db.flush()
    return db_collaborator


def set_collaborator_termination(
    db: Session,
    db_collaborator: Collaborator,
    termination_date: date,
) -> Collaborator:
    """POST /{id}/terminate (§9, BR-LIQ-01): status terminated + the
    date; the motor run that produces the LIQ seats happens in the API
    layer within the SAME transaction (T-05)."""
    db_collaborator.status = "terminated"
    db_collaborator.termination_date = termination_date
    db.flush()
    return db_collaborator


# ──────────────────────────────────────────────────
# Salary plans (§4.2, BR-02/BR-COLLAB-02)
# ──────────────────────────────────────────────────

def get_salary_plans(
    db: Session, id_collaborator: int
) -> List[CollaboratorSalaryPlan]:
    """All vigencias of a collaborator ordered by valid_from."""
    return db.query(CollaboratorSalaryPlan).filter(
        CollaboratorSalaryPlan.id_collaborator == id_collaborator
    ).order_by(CollaboratorSalaryPlan.valid_from).all()


def get_open_salary_plan(
    db: Session, id_collaborator: int
) -> Optional[CollaboratorSalaryPlan]:
    """The current OPEN plan (valid_to NULL) with the latest valid_from."""
    return db.query(CollaboratorSalaryPlan).filter(
        CollaboratorSalaryPlan.id_collaborator == id_collaborator,
        CollaboratorSalaryPlan.valid_to.is_(None),
    ).order_by(CollaboratorSalaryPlan.valid_from.desc()).first()


def apply_salary_plan(
    db: Session,
    db_collaborator: Collaborator,
    salary: Decimal,
    allowance_salary: Decimal,
    allowance_non_salary: Decimal,
    is_integral: bool,
    valid_from: date,
    force_new_vigencia: bool = False,
) -> str:
    """Upsert semantics of R-07/BR-02 for one salary row:

    - no plan yet                       -> alta (\"created\")
    - identical values                  -> no-op (\"no_change\")
      REGARDLESS of the imported date: a blank Fecha de Aumento on a
      re-import of an EXISTING collaborator resolves to TODAY at the
      endpoint, so re-importing the same file on a later day stays
      idempotent (AC-PLT-2). force_new_vigencia (explicit POST
      /{id}/salary-plan) overrides the guard — the user IS asking for a
      new vigencia with those values.
    - same valid_from, different values -> the plan is still OPEN, so it
      IS the current vigencia: updated in place (\"updated\")
    - new later valid_from, new values  -> close the open plan
      (valid_to = valid_from - 1) and append the new vigencia
      (\"updated\") — closed history is NEVER edited (BR-02)
    - valid_from before the open plan   -> historical backfill is out of
      scope in v1 (A-10): no-op (\"no_change\")

    Returns the action label; never commits (T-05)."""
    open_plan = get_open_salary_plan(db, db_collaborator.id_collaborator)

    if open_plan is None:
        db.add(CollaboratorSalaryPlan(
            id_collaborator=db_collaborator.id_collaborator,
            salary=salary,
            allowance_salary=allowance_salary,
            allowance_non_salary=allowance_non_salary,
            is_integral=is_integral,
            valid_from=valid_from,
        ))
        db.flush()
        return "created"

    same_values = (
        Decimal(open_plan.salary) == Decimal(salary)
        and Decimal(open_plan.allowance_salary or 0) == Decimal(allowance_salary)
        and Decimal(open_plan.allowance_non_salary or 0) == Decimal(allowance_non_salary)
        and bool(open_plan.is_integral) == bool(is_integral)
    )

    if same_values and not force_new_vigencia:
        return "no_change"

    if valid_from == open_plan.valid_from:
        open_plan.salary = salary
        open_plan.allowance_salary = allowance_salary
        open_plan.allowance_non_salary = allowance_non_salary
        open_plan.is_integral = is_integral
        db.flush()
        return "updated"

    if valid_from > open_plan.valid_from:
        # New vigencia (raise/incremento): close the open plan the day
        # before and append — BR-02 (aumentos create a vigencia, they do
        # not edit a closed one).
        open_plan.valid_to = valid_from - timedelta(days=1)
        db.add(CollaboratorSalaryPlan(
            id_collaborator=db_collaborator.id_collaborator,
            salary=salary,
            allowance_salary=allowance_salary,
            allowance_non_salary=allowance_non_salary,
            is_integral=is_integral,
            valid_from=valid_from,
        ))
        db.flush()
        return "updated"

    # valid_from in the past relative to the open vigencia: backfill is
    # deliberately not modeled in v1 (A-10, cero recálculo retroactivo).
    return "no_change"


# ──────────────────────────────────────────────────
# Labor parameters & ARL rates (§4.3/§4.4)
# ──────────────────────────────────────────────────

def get_labor_parameters(
    db: Session, vigencia: int
) -> List[LaborCostParameter]:
    """Key/value catalog rows of one vigencia (§9 GET)."""
    return db.query(LaborCostParameter).filter(
        LaborCostParameter.vigencia == vigencia
    ).order_by(LaborCostParameter.key).all()


def get_labor_parameters_dict(
    db: Session, vigencia: int
) -> Dict[str, str]:
    """Motor-facing view: key -> Decimal(value). Empty dict when the
    vigencia has no parameters at all — the ENGINE (not this helper)
    turns that into the structured R-05/BR-03 error: it never guesses
    rates (D-S11-9)."""
    rows = get_labor_parameters(db, vigencia)
    return {row.key: row.value for row in rows if row.value}


def upsert_labor_parameters(
    db: Session, vigencia: int, values: Dict[str, str]
) -> int:
    """PUT /budget/labor-params (§9): update-in-place or insert per
    (vigencia, key). Returns the number of keys touched. Values arrive as
    strings from the wire contract (§4.3 stores strings, D-S11-4 parses
    at read)."""
    touched = 0
    for key, value in values.items():
        row = db.query(LaborCostParameter).filter(
            LaborCostParameter.vigencia == vigencia,
            LaborCostParameter.key == key,
        ).first()
        if row is None:
            db.add(LaborCostParameter(
                vigencia=vigencia, key=key, value=str(value),
            ))
        else:
            row.value = str(value)
        touched += 1
    db.flush()
    return touched


def get_labor_arl_rates(
    db: Session, vigencia: int
) -> Dict[str, Decimal]:
    """risk_class -> rate of one vigencia (Decimal straight from
    DECIMAL(9,6), D-S11-4)."""
    rows = db.query(LaborArlRate).filter(
        LaborArlRate.vigencia == vigencia
    ).all()
    return {row.risk_class: Decimal(row.rate) for row in rows}


def upsert_labor_arl_rates(
    db: Session, vigencia: int, rates: Dict[str, Decimal]
) -> int:
    """Companion of the parameters PUT (NFR-06: a new annual vigencia is
    created WITHOUT touching code)."""
    touched = 0
    for risk_class, rate in rates.items():
        row = db.query(LaborArlRate).filter(
            LaborArlRate.vigencia == vigencia,
            LaborArlRate.risk_class == risk_class,
        ).first()
        if row is None:
            db.add(LaborArlRate(
                vigencia=vigencia, risk_class=risk_class, rate=Decimal(rate),
            ))
        else:
            row.rate = Decimal(rate)
        touched += 1
    db.flush()
    return touched


# ──────────────────────────────────────────────────
# Cost components (§4.5) — read-only catalog
# ──────────────────────────────────────────────────

def get_cost_components(
    db: Session, active_only: bool = True
) -> List[CostComponent]:
    """GET /budget/cost-components: active by default (the extralegales
    stay seeded with is_active=False, A-11/R-12)."""
    query = db.query(CostComponent)
    if active_only:
        query = query.filter(CostComponent.is_active.is_(True))
    return query.order_by(CostComponent.code).all()


def get_cost_component_map(db: Session) -> Dict[str, CostComponent]:
    """code -> row for the motor (ALL rows; the motor itself filters
    is_active per component emission, R-12)."""
    return {row.code: row for row in db.query(CostComponent).all()}


# ──────────────────────────────────────────────────
# Provision accruals (§4.6, D-S11-3)
# ──────────────────────────────────────────────────

def get_provision_accruals(
    db: Session,
    id_collaborator: int,
    component_code: Optional[str] = None,
) -> List[CollaboratorProvisionAccrual]:
    """Ledger rows of a collaborator ordered by (component, month)."""
    query = db.query(CollaboratorProvisionAccrual).filter(
        CollaboratorProvisionAccrual.id_collaborator == id_collaborator
    )
    if component_code:
        query = query.filter(
            CollaboratorProvisionAccrual.component_code == component_code
        )
    return query.order_by(
        CollaboratorProvisionAccrual.component_code,
        CollaboratorProvisionAccrual.period_month,
    ).all()


def get_provision_balances(
    db: Session, id_collaborator: int
) -> List[Tuple[str, Decimal, Decimal]]:
    """GET /{id}/provisions: [(component_code, Σaccrued, Σpaid)] — the
    balance is derived (Σacc − Σpag), never stored (§9)."""
    rows = get_provision_accruals(db, id_collaborator)
    totals: Dict[str, List[Decimal]] = {}
    for row in rows:
        acc, paid = totals.setdefault(
            row.component_code, [Decimal("0"), Decimal("0")]
        )
        totals[row.component_code] = [acc + Decimal(row.accrued),
                                      paid + Decimal(row.paid)]
    return [(code, acc_paid[0], acc_paid[1])
            for code, acc_paid in sorted(totals.items())]


def accruals_in_range(
    db: Session,
    id_collaborator: int,
    component_code: str,
    month_from_first: date,
    month_to_last: date,
) -> List[CollaboratorProvisionAccrual]:
    """Rows of one component whose period_month falls in a payment
    period (§5.3: ene–jun prima, full previous year cesantías/intereses)."""
    return db.query(CollaboratorProvisionAccrual).filter(
        CollaboratorProvisionAccrual.id_collaborator == id_collaborator,
        CollaboratorProvisionAccrual.component_code == component_code,
        CollaboratorProvisionAccrual.period_month >= month_from_first,
        CollaboratorProvisionAccrual.period_month <= month_to_last,
    ).all()


def upsert_provision_accrual(
    db: Session,
    id_collaborator: int,
    component_code: str,
    period_month: date,
    accrued: Decimal,
    params_vigencia: int,
) -> CollaboratorProvisionAccrual:
    """Motor causacion write: (collaborator, component, month) is UNIQUE
    (§4.6) — existing row keeps its ``paid`` mark and updates ``accrued``
    (the run deletes the month rows first, so normally this INSERTs
    fresh; the update branch keeps the helper safe for partial windows).
    paid is ONLY marked by the motor (D-S11-3, A-05)."""
    row = db.query(CollaboratorProvisionAccrual).filter(
        CollaboratorProvisionAccrual.id_collaborator == id_collaborator,
        CollaboratorProvisionAccrual.component_code == component_code,
        CollaboratorProvisionAccrual.period_month == period_month,
    ).first()
    if row is None:
        row = CollaboratorProvisionAccrual(
            id_collaborator=id_collaborator,
            component_code=component_code,
            period_month=period_month,
            accrued=accrued,
            paid=Decimal("0"),
            params_vigencia=params_vigencia,
        )
        db.add(row)
    else:
        row.accrued = accrued
        row.params_vigencia = params_vigencia
    db.flush()
    return row


def delete_provision_accruals_for_month(
    db: Session, id_collaborator: int, month_first: date
) -> int:
    """Physical delete of the collaborator's causacion rows of ONE month
    (part of the R-13 idempotent replacement: the run window recreates
    them deterministically from the plan + vigencia params)."""
    return db.query(CollaboratorProvisionAccrual).filter(
        CollaboratorProvisionAccrual.id_collaborator == id_collaborator,
        CollaboratorProvisionAccrual.period_month == month_first,
    ).delete(synchronize_session=False)


def mark_accruals_paid(
    db: Session, rows: List[CollaboratorProvisionAccrual]
) -> None:
    """D-S11-3 closure: paid = accrued for the period rows (the payment
    seat always brings the balance to EXACTLY 0 — never recomputed from
    the rate)."""
    for row in rows:
        row.paid = row.accrued
    db.flush()


def reset_accruals_paid(
    db: Session, rows: List[CollaboratorProvisionAccrual]
) -> None:
    """Idempotent-run hygiene: the run window is about to DELETE and
    recreate the payment seats that produced the ``paid`` marks of these
    period rows, so their marks are cleared first and re-set by the
    recreated seat (otherwise a re-run would double-deduct and the
    settlement seat under-pay). Only ever applied to periods whose
    payment month falls INSIDE the run window (run_projection)."""
    for row in rows:
        row.paid = Decimal("0")
    db.flush()


def reset_all_accruals_paid(db: Session, id_collaborator: int) -> None:
    """Clear every ``paid`` mark of a collaborator's ledger (the run
    covers a liquidation month — the LIQ seat re-pays the full remaining
    balance and legal payment seats before it re-mark their own
    periods)."""
    rows = db.query(CollaboratorProvisionAccrual).filter(
        CollaboratorProvisionAccrual.id_collaborator == id_collaborator
    ).all()
    reset_accruals_paid(db, rows)


# ──────────────────────────────────────────────────
# Motor-owned budget_lines (R-13 / BR-09)
# ──────────────────────────────────────────────────

def delete_collaborator_engine_lines(
    db: Session,
    id_collaborator: int,
    month_first: Optional[date] = None,
    month_last: Optional[date] = None,
) -> int:
    """R-13 idempotent replacement: physical delete of the MATERIALIZED
    lines of this collaborator for ONE month (or a closed range), and
    ONLY rows the motor owns — ``source_engine LIKE 'collaborator_%'``
    AND id_collaborator = X (spec §7 invariant: manual lines, other
    templates and the REAL side coexist untouched; the source_engine
    predicate alone already excludes every legacy row because it is NULL
    there, D-S11-5). Returns deleted count."""
    query = db.query(BudgetLineModel).filter(
        BudgetLineModel.id_collaborator == id_collaborator,
        BudgetLineModel.source_engine.like(ENGINE_SOURCE_PATTERN),
    )
    if month_first is not None:
        query = query.filter(BudgetLineModel.budget_date >= month_first)
    if month_last is not None:
        query = query.filter(BudgetLineModel.budget_date <= month_last)
    return query.delete(synchronize_session=False)


def delete_collaborator_engine_component_months(
    db: Session,
    id_collaborator: int,
    component_code: str,
    month_firsts: List[date],
) -> int:
    """R-13-scoped delete for the liquidación replacement (§5.5): remove
    ONLY the motor's causacion lines of ONE component for the given
    months — the LIQ seat absorbs their projected cash so keeping them
    would double-count. Same engine-ownership predicates as
    delete_collaborator_engine_lines (source_engine LIKE + id +
    component); never touches other rows."""
    if not month_firsts:
        return 0
    month_filters = []
    for m_first in month_firsts:
        m_last = date(
            m_first.year, m_first.month,
            monthrange(m_first.year, m_first.month)[1],
        )
        month_filters.append(and_(
            BudgetLineModel.budget_date >= m_first,
            BudgetLineModel.budget_date <= m_last,
        ))
    return db.query(BudgetLineModel).filter(
        BudgetLineModel.id_collaborator == id_collaborator,
        BudgetLineModel.source_engine.like(ENGINE_SOURCE_PATTERN),
        BudgetLineModel.cost_component_code == component_code,
        or_(*month_filters),
    ).delete(synchronize_session=False)


def insert_collaborator_engine_lines(
    db: Session, rows: List[Dict[str, Any]]
) -> int:
    """Bulk add of the motor's BudgetLine dicts (no commit — T-05; the
    line already carries id_budget/id_cost_center/line_type='expense'/
    behavior_type='fixed'/budget_date/payment_date/projected_amount/
    description/id_collection + the three D-S11-5 link columns)."""
    for data in rows:
        db.add(BudgetLineModel(**data))
    db.flush()
    return len(rows)


# ──────────────────────────────────────────────────
# Scenario resolution (D-S11-8)
# ──────────────────────────────────────────────────

def get_active_budget_for_year(
    db: Session, year: int
) -> Optional[BudgetModel]:
    """The active target of a fiscal year (BR-TGT-01 invariant guarantees
    at most one; lowest id_budget mirrors the budgetEngine tie-break).
    None = no active scenario for that year: the D-S11-8 window falls
    back to 31/12 of the natural year and materialization is skipped
    with a warning (accruals and the live breakdown are unaffected)."""
    return db.query(BudgetModel).filter(
        BudgetModel.budget_year == year,
        BudgetModel.status == "active",
    ).order_by(BudgetModel.id_budget).first()


# ── Opcion C/A enmienda (set-target materialization + status) ──

def list_active_collaborators(db: Session) -> List[Collaborator]:
    """All status='active' collaborators (the population the set-target
    hook materializes; ordered by id for a deterministic run)."""
    return db.query(Collaborator).filter(
        Collaborator.status == "active"
    ).order_by(Collaborator.id_collaborator).all()


def count_active_collaborators(db: Session) -> int:
    return db.query(Collaborator).filter(
        Collaborator.status == "active"
    ).count()


def count_collaborators_with_open_plan(db: Session) -> int:
    """Distinct collaborators with at least one OPEN plan (valid_to NULL):
    the population the motor is able to project (banner Opcion A)."""
    rows = db.query(CollaboratorSalaryPlan.id_collaborator).filter(
        CollaboratorSalaryPlan.valid_to.is_(None)
    ).distinct().all()
    return len(rows)


def count_engine_lines_for_budget(db: Session, id_budget: int) -> int:
    """Motor-owned budget_lines of one scenario (same ENGINE_SOURCE_PATTERN
    predicate as R-13, never broader)."""
    return db.query(BudgetLineModel).filter(
        BudgetLineModel.id_budget == id_budget,
        BudgetLineModel.source_engine.like(ENGINE_SOURCE_PATTERN),
    ).count()


# ──────────────────────────────────────────────────
# Physical delete of the collaborator (S12-COLLAB-DELETE)
# ──────────────────────────────────────────────────

def delete_collaborator(db: Session, collab: Collaborator) -> Dict[str, int]:
    """S12-COLLAB-DELETE: PERMANENT physical delete of the master + ALL
    its dependents, atomic — the CALLER owns the single db.commit()
    (T-05). This is the ONLY allowed history DELETE of the module
    (NFR-03 exception: scoped to exactly one collaborator; every other
    route — terminate, vigencias — preserves the historics).

    Order matters: budget_lines carry id_collaborator as a plain
    Integer with NO DB FK, so the motor-owned rows are deleted
    EXPLICITLY first (BR-D2) — the ORM cascade can never reach them.
    The children are counted BEFORE db.delete() because the ORM
    cascade ("all, delete-orphan") empties both collections at flush
    time. Returns the deletion summary for audit + the FE toast."""
    # No FK ⇒ explicit delete of every engine line of every
    # scenario/year, otherwise the master's delete would orphan them.
    deleted_budget_lines = delete_collaborator_engine_lines(
        db, collab.id_collaborator
    )
    deleted_salary_plans = len(collab.salary_plans)
    deleted_provision_accruals = len(collab.provision_accruals)
    # ORM cascade deletes the plans and the causacion ledger with the
    # master (delete-orphan on both relationships).
    db.delete(collab)
    return {
        "deleted_salary_plans": deleted_salary_plans,
        "deleted_provision_accruals": deleted_provision_accruals,
        "deleted_budget_lines": deleted_budget_lines,
    }
