"""Transactional workflow and budget expense materialization for financing."""

from decimal import Decimal
from datetime import date
from typing import Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.budget import (
    Budget, BudgetLine, CostCenter, FinancingCredit, FinancingCreditInstallment,
)
from app.models.budget.budgetLine import BehaviorTypeEnum, LineTypeEnum
from app.schemas.budget.financingCredit import FinancingCreditCreate
from app.services.budget.financingCreditEngine import (
    FinancingScheduleError, InstallmentProjection, add_months, generate_schedule,
)


ZERO = Decimal("0.00")
ENGINE = "financing_credit"


def _load_credit(db: Session, id_financing_credit: int, lock: bool = False):
    query = db.query(FinancingCredit).filter(
        FinancingCredit.id_financing_credit == id_financing_credit
    )
    if lock:
        query = query.with_for_update()
    return query.first()


def _active_installments(db: Session, credit: FinancingCredit):
    if credit.status != "active":
        return []
    return (db.query(FinancingCreditInstallment).filter(
        FinancingCreditInstallment.id_financing_credit == credit.id_financing_credit,
        FinancingCreditInstallment.schedule_revision == credit.schedule_revision,
    ).order_by(FinancingCreditInstallment.installment_number).all())


def _schedule_conditions(data: dict):
    start = data["disbursement_date"] if data["origin_type"] == "new" else data["cutoff_date"]
    date_anchor = (
        data["disbursement_date"]
        if data["origin_type"] == "new"
        else data["first_due_date"]
    )
    first_due_month_offset = 1 if data["origin_type"] == "new" else 0
    try:
        schedule = generate_schedule(
            opening_balance=data["opening_balance"],
            annual_rate=data["annual_rate"],
            rate_convention=data["rate_convention"],
            day_count_convention=data["day_count_convention"],
            method=data["method"],
            term_installments=data["term_installments"],
            first_due_date=data["first_due_date"],
            schedule_start_date=start,
            insurance_per_installment=data["insurance_per_installment"],
            date_anchor=date_anchor,
            first_due_month_offset=first_due_month_offset,
        )
    except FinancingScheduleError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_schedule"}) from exc
    return schedule


def _normalized_conditions(payload: FinancingCreditCreate) -> FinancingCreditCreate:
    """Resolve server-owned defaults before previewing or persisting conditions."""
    if payload.origin_type == "new" and payload.first_due_date is None:
        return payload.model_copy(update={
            "first_due_date": add_months(payload.disbursement_date, 1),
        })
    return payload


def _totals(rows) -> dict:
    principal = sum((Decimal(str(row.principal_amount)) for row in rows), ZERO)
    interest = sum((Decimal(str(row.interest_amount)) for row in rows), ZERO)
    insurance = sum((Decimal(str(row.insurance_amount)) for row in rows), ZERO)
    return {
        "principal": principal,
        "interest": interest,
        "insurance": insurance,
        "total_cash_outflow": principal + interest + insurance,
    }


def _projection_out(row: InstallmentProjection, id_credit=None, revision=None,
                    id_cost_center=None):
    return {
        "id_financing_credit": id_credit,
        "installment_number": row.installment_number,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "principal_amount": row.principal_amount,
        "principal_due_date": row.period_end,
        "interest_amount": row.interest_amount,
        "interest_due_date": row.period_end,
        "insurance_amount": row.insurance_amount,
        "insurance_due_date": row.period_end,
        "opening_balance": row.opening_balance,
        "closing_balance": row.closing_balance,
        "rate_used": row.rate_used,
        "rate_convention": row.rate_convention,
        "day_count_convention": row.day_count_convention,
        "method": row.method,
        "id_cost_center": id_cost_center,
        "schedule_revision": revision,
        "projection_status": "projected",
        "total_amount": row.total_amount,
    }


def preview_financing_credit(db: Session, payload: FinancingCreditCreate):
    if db.query(CostCenter).filter(CostCenter.id_cost_center == payload.id_cost_center).first() is None:
        raise HTTPException(status_code=404, detail={"message": "Cost center not found", "field": "id_cost_center"})
    conditions = _normalized_conditions(payload)
    rows = _schedule_conditions(conditions.model_dump())
    return {
        "conditions": conditions,
        "schedule": [
            _projection_out(row, id_cost_center=payload.id_cost_center)
            for row in rows
        ],
        "totals": _totals(rows),
        "warnings": [],
    }


def _active_budgets_for_year(db: Session, year: int, id_budget=None):
    """Return active targets for a year, including scenario targets.

    Draft and closed budgets are deliberately not persistence destinations:
    they display financing costs through the read-only simulation endpoint.
    ``id_budget`` is passed by set-target so the newly activated target is
    explicitly included even if historical data has unusual scenario flags.
    """
    budgets = (db.query(Budget).filter(
        Budget.budget_year == year,
        Budget.status == "active",
    ).order_by(Budget.id_budget).all())
    if id_budget is not None:
        explicit = db.query(Budget).filter(
            Budget.id_budget == id_budget,
            Budget.budget_year == year,
            Budget.status == "active",
        ).first()
        if explicit is not None and all(
            row.id_budget != explicit.id_budget for row in budgets
        ):
            budgets.append(explicit)
    return budgets


def _no_active_budget_warning(year: int) -> str:
    return (
        f"No active target for {year}; financing expenses are simulated in "
        "draft/closed budgets and materialize when a target is activated"
    )


def _missing_budget_lines_warning(credit: FinancingCredit, year: int,
                                  budget: Budget, missing_count: int) -> str:
    return (
        f"{missing_count} expected FIN_INTEREST/FIN_INSURANCE budget line(s) "
        f"are missing for {year} in selected budget id_budget={budget.id_budget}; "
        f"execute POST /budget/financing-credit/{credit.id_financing_credit}/recalculate "
        'to repair the active target materialization'
    )


def _materialize_expenses(db: Session, credit: FinancingCredit,
                          installments: List[FinancingCreditInstallment],
                          id_budget=None) -> Tuple[int, List[str]]:
    warnings: List[str] = []
    budget_by_year: Dict[int, List[Budget]] = {}
    materialized = 0
    for installment in installments:
        if (Decimal(str(installment.interest_amount)) <= ZERO
                and Decimal(str(installment.insurance_amount)) <= ZERO):
            continue
        year = installment.period_end.year
        if year not in budget_by_year:
            budgets = _active_budgets_for_year(db, year, id_budget=id_budget)
            budget_by_year[year] = budgets
            if not budgets:
                warnings.append(_no_active_budget_warning(year))
            elif len(budgets) > 1:
                warnings.append(
                    f"Multiple active targets in {year} ({len(budgets)}); "
                    "financing expenses materialized in each active target"
                )
        budgets = budget_by_year[year]
        if not budgets:
            continue
        components = (
            ("FIN_INTEREST", installment.interest_amount, installment.interest_due_date, "Interest"),
            ("FIN_INSURANCE", installment.insurance_amount, installment.insurance_due_date, "Insurance"),
        )
        for budget in budgets:
            for code, amount, due_date, label in components:
                amount = Decimal(str(amount))
                if amount <= ZERO:
                    continue
                existing = db.query(BudgetLine).filter(
                    BudgetLine.id_budget == budget.id_budget,
                    BudgetLine.source_engine == ENGINE,
                    BudgetLine.source_engine_id == installment.id_financing_credit_installment,
                    BudgetLine.cost_component_code == code,
                ).first()
                if existing is not None:
                    continue
                db.add(BudgetLine(
                    id_budget=budget.id_budget,
                    id_cost_center=credit.id_cost_center,
                    line_type=LineTypeEnum.EXPENSE,
                    behavior_type=BehaviorTypeEnum.FIXED,
                    budget_date=installment.period_end,
                    payment_date=due_date,
                    projected_amount=amount,
                    description=(f"{label} — {credit.lender_name} — "
                                 f"{credit.name} — installment {installment.installment_number}"),
                    # IVA fix 2026-10-26: interest/insurance of a credit are
                    # non-taxed for the borrower (NULL would be read as
                    # "con IVA" by the liquidation engine and the FE flow
                    # gross-up — D-S10-3 rule). EXPLICIT False.
                    has_iva=False,
                    source_engine=ENGINE,
                    source_engine_id=installment.id_financing_credit_installment,
                    cost_component_code=code,
                ))
                materialized += 1
    db.flush()
    return materialized, warnings


def _replace_schedule(db: Session, credit: FinancingCredit, schedule,
                      replaced_installments: int) -> dict:
    previous = db.query(FinancingCreditInstallment).filter(
        FinancingCreditInstallment.id_financing_credit == credit.id_financing_credit
    ).all()
    old_ids = [row.id_financing_credit_installment for row in previous]
    replaced_lines = 0
    if old_ids:
        old_lines = db.query(BudgetLine).filter(
            BudgetLine.source_engine == ENGINE,
            BudgetLine.source_engine_id.in_(old_ids),
        ).all()
        replaced_lines = len(old_lines)
        for line in old_lines:
            db.delete(line)

    credit.schedule_revision += 1
    new_rows = []
    for projection in schedule:
        installment = FinancingCreditInstallment(
            id_financing_credit=credit.id_financing_credit,
            installment_number=projection.installment_number,
            period_start=projection.period_start,
            period_end=projection.period_end,
            principal_amount=projection.principal_amount,
            principal_due_date=projection.period_end,
            interest_amount=projection.interest_amount,
            interest_due_date=projection.period_end,
            insurance_amount=projection.insurance_amount,
            insurance_due_date=projection.period_end,
            opening_balance=projection.opening_balance,
            closing_balance=projection.closing_balance,
            rate_used=projection.rate_used,
            rate_convention=projection.rate_convention,
            day_count_convention=projection.day_count_convention,
            method=projection.method,
            id_cost_center=credit.id_cost_center,
            schedule_revision=credit.schedule_revision,
            projection_status="projected",
        )
        db.add(installment)
        new_rows.append(installment)
    db.flush()
    created_lines, warnings = _materialize_expenses(db, credit, new_rows)
    return {
        "schedule_revision": credit.schedule_revision,
        "replaced_installments": replaced_installments,
        "created_installments": len(new_rows),
        "replaced_budget_lines": replaced_lines,
        "created_budget_lines": created_lines,
        "warnings": warnings,
    }


def create_financing_credit(db: Session, payload: FinancingCreditCreate):
    if db.query(CostCenter).filter(CostCenter.id_cost_center == payload.id_cost_center).first() is None:
        raise HTTPException(status_code=404, detail={"message": "Cost center not found", "field": "id_cost_center"})
    conditions = _normalized_conditions(payload)
    data = conditions.model_dump()
    schedule = _schedule_conditions(data)
    credit = FinancingCredit(**data, status="active", schedule_revision=0)
    db.add(credit)
    db.flush()
    generation = _replace_schedule(db, credit, schedule, 0)
    return credit, generation


def update_financing_credit(db: Session, id_financing_credit: int, changes: dict):
    credit = _load_credit(db, id_financing_credit, lock=True)
    if credit is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    if credit.status != "active":
        raise HTTPException(status_code=400, detail={"message": "Closed financing credits cannot be edited"})
    values = {
        column.name: getattr(credit, column.name)
        for column in FinancingCredit.__table__.columns
        if column.name in FinancingCreditCreate.model_fields
    }
    changed = any(getattr(credit, key) != value for key, value in changes.items())
    values.update(changes)
    try:
        normalized = FinancingCreditCreate(**values)
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_conditions"}) from exc
    if not changed:
        return credit, {
            "schedule_revision": credit.schedule_revision,
            "replaced_installments": 0, "created_installments": 0,
            "replaced_budget_lines": 0, "created_budget_lines": 0,
            "warnings": [],
        }
    if db.query(CostCenter).filter(CostCenter.id_cost_center == normalized.id_cost_center).first() is None:
        raise HTTPException(status_code=404, detail={"message": "Cost center not found", "field": "id_cost_center"})
    schedule = _schedule_conditions(normalized.model_dump())
    old_active_count = len(_active_installments(db, credit))
    for key, value in normalized.model_dump().items():
        setattr(credit, key, value)
    db.flush()
    generation = _replace_schedule(db, credit, schedule, old_active_count)
    return credit, generation


def recalculate_financing_credit(db: Session, id_financing_credit: int):
    credit = _load_credit(db, id_financing_credit, lock=True)
    if credit is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    if credit.status != "active":
        raise HTTPException(status_code=400, detail="Closed financing credits cannot be recalculated")
    active = _active_installments(db, credit)
    # Identical recalculation is a no-op: preserve active IDs and all owned
    # expense lines. Missing lines may be materialized if an active target
    # became available since the previous generation.
    if len(active) == credit.term_installments:
        created_lines, warnings = _materialize_expenses(db, credit, active)
        return {
            "schedule_revision": credit.schedule_revision,
            "replaced_installments": 0, "created_installments": 0,
            "replaced_budget_lines": 0, "created_budget_lines": created_lines,
            "warnings": warnings,
        }
    data = {key: getattr(credit, key) for key in FinancingCreditCreate.model_fields}
    schedule = _schedule_conditions(data)
    generation = _replace_schedule(db, credit, schedule, len(active))
    return generation


def close_financing_credit(db: Session, id_financing_credit: int,
                           cutoff_date: date, remaining_balance: Decimal):
    credit = _load_credit(db, id_financing_credit, lock=True)
    if credit is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    if credit.status == "closed":
        return credit, 0
    remaining_balance = Decimal(str(remaining_balance))
    if cutoff_date > date.today():
        raise HTTPException(status_code=400, detail={"message": "cutoff_date cannot be in the future"})
    if remaining_balance != ZERO:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "A positive remaining balance cannot be closed; update the credit conditions and regenerate its schedule instead.",
                "field": "remaining_balance",
                "code": "balance_remains",
            },
        )
    active = _active_installments(db, credit)
    active_ids = [row.id_financing_credit_installment for row in active]
    removed = 0
    if active_ids:
        owned = db.query(BudgetLine).filter(
            BudgetLine.source_engine == ENGINE,
            BudgetLine.source_engine_id.in_(active_ids),
        ).all()
        removed = len(owned)
        for line in owned:
            db.delete(line)
    for installment in active:
        installment.projection_status = "suspended"
    credit.status = "closed"
    credit.closure_date = cutoff_date
    credit.closure_balance = remaining_balance
    db.flush()
    return credit, len(active)


def delete_financing_credit(db: Session, id_financing_credit: int) -> dict:
    """Permanently remove a financing credit and all its projections.

    The API commits this operation once through ``_commit_or_rollback``;
    this service intentionally neither commits nor soft-deletes. It applies
    equally to active and closed credits (closing remains a separate action).
    """
    # Import lazily: app.crud is a broad legacy re-export package whose import
    # graph reaches app.core.auth -> app.api while API modules load.
    import app.crud as crud

    result = crud.delete_financing_credit(db, id_financing_credit)
    if result is None:
        raise HTTPException(status_code=404, detail="Financing credit not found")
    return result


def materialize_financing_for_scenario_year(
    db: Session, year: int, id_budget=None,
) -> dict:
    """Materialize financing expenses for active credits after target activation.

    Called after set-target's own commit. Errors are returned as warnings and
    never invalidate that activation. The helper commits/rolls back its own
    transaction and is idempotent by budget/installment/component identity.
    """
    out = {"lines_created": 0, "credits": 0, "warnings": []}
    try:
        budgets = _active_budgets_for_year(db, year, id_budget=id_budget)
        if not budgets:
            out["warnings"].append(_no_active_budget_warning(year))
            return out
        credits = db.query(FinancingCredit).filter(
            FinancingCredit.status == "active",
        ).order_by(FinancingCredit.id_financing_credit).all()
        for credit in credits:
            installments = (db.query(FinancingCreditInstallment).filter(
                FinancingCreditInstallment.id_financing_credit == credit.id_financing_credit,
                FinancingCreditInstallment.schedule_revision == credit.schedule_revision,
                FinancingCreditInstallment.period_end >= date(year, 1, 1),
                FinancingCreditInstallment.period_end < date(year + 1, 1, 1),
                FinancingCreditInstallment.projection_status == "projected",
            ).order_by(FinancingCreditInstallment.installment_number).all())
            if not installments:
                continue
            out["credits"] += 1
            created, warnings = _materialize_expenses(
                db, credit, installments, id_budget=id_budget,
            )
            out["lines_created"] += created
            out["warnings"].extend(warnings)
        db.commit()
    except Exception as exc:
        db.rollback()
        out["warnings"].append(f"financing materialization failed: {exc}")
    return out


def simulate_financing_year(db: Session, year: int) -> dict:
    """Read-only FIN_INTEREST/FIN_INSURANCE simulation for a budget year."""
    rows = (db.query(FinancingCreditInstallment, FinancingCredit)
        .join(FinancingCredit, FinancingCredit.id_financing_credit ==
              FinancingCreditInstallment.id_financing_credit)
        .filter(
            FinancingCredit.status == "active",
            FinancingCreditInstallment.schedule_revision == FinancingCredit.schedule_revision,
            FinancingCreditInstallment.period_end >= date(year, 1, 1),
            FinancingCreditInstallment.period_end < date(year + 1, 1, 1),
            FinancingCreditInstallment.projection_status == "projected",
        )
        .order_by(FinancingCreditInstallment.period_end,
                  FinancingCredit.id_financing_credit,
                  FinancingCreditInstallment.installment_number).all())
    lines = []
    interest_total = ZERO
    insurance_total = ZERO
    credit_ids = set()
    for installment, credit in rows:
        components = (
            ("FIN_INTEREST", installment.interest_amount,
             installment.interest_due_date, "Interest"),
            ("FIN_INSURANCE", installment.insurance_amount,
             installment.insurance_due_date, "Insurance"),
        )
        for code, raw_amount, payment_date, label in components:
            amount = Decimal(str(raw_amount))
            if amount <= ZERO:
                continue
            credit_ids.add(credit.id_financing_credit)
            if code == "FIN_INTEREST":
                interest_total += amount
            else:
                insurance_total += amount
            lines.append({
                "month": installment.period_end.strftime("%Y-%m"),
                "budget_date": installment.period_end,
                "payment_date": payment_date,
                "id_cost_center": credit.id_cost_center,
                "cost_component_code": code,
                "component_name": label,
                "description": (
                    f"{label} — {credit.lender_name} — {credit.name} — "
                    f"installment {installment.installment_number}"
                ),
                "amount": amount,
                "id_financing_credit": credit.id_financing_credit,
                "id_financing_credit_installment": installment.id_financing_credit_installment,
            })
    return {
        "budget_year": year,
        "financing_credits_count": len(credit_ids),
        "total_interest": interest_total,
        "total_insurance": insurance_total,
        "total_annual_expenses": interest_total + insurance_total,
        "lines": lines,
    }


def serialize_credit(db: Session, credit: FinancingCredit, include_installments=False):
    installments = _active_installments(db, credit)
    warnings: List[str] = []
    expected_by_year: Dict[int, set[Tuple[int, str]]] = {}
    for row in installments:
        components = []
        if Decimal(str(row.interest_amount)) > ZERO:
            components.append("FIN_INTEREST")
        if Decimal(str(row.insurance_amount)) > ZERO:
            components.append("FIN_INSURANCE")
        if components:
            expected_by_year.setdefault(row.period_end.year, set()).update(
                (row.id_financing_credit_installment, code)
                for code in components
            )

    for year in sorted(expected_by_year):
        budgets = _active_budgets_for_year(db, year)
        if not budgets:
            warnings.append(
                _no_active_budget_warning(year)
            )
            continue
        expected = expected_by_year[year]
        installment_ids = {installment_id for installment_id, _code in expected}
        for budget in budgets:
            present = set(db.query(
                BudgetLine.source_engine_id, BudgetLine.cost_component_code,
            ).filter(
                BudgetLine.id_budget == budget.id_budget,
                BudgetLine.source_engine == ENGINE,
                BudgetLine.source_engine_id.in_(installment_ids),
                BudgetLine.cost_component_code.in_(
                    ("FIN_INTEREST", "FIN_INSURANCE"),
                ),
            ).all())
            missing_count = len(expected - present)
            if missing_count:
                warnings.append(
                    _missing_budget_lines_warning(credit, year, budget, missing_count)
                )
    result = {
        "id_financing_credit": credit.id_financing_credit,
        "name": credit.name,
        "lender_name": credit.lender_name,
        "credit_type": credit.credit_type,
        "status": credit.status,
        "origin_type": credit.origin_type,
        "id_cost_center": credit.id_cost_center,
        "method": credit.method,
        "currency": credit.currency,
        "disbursement_date": credit.disbursement_date,
        "original_principal": credit.original_principal,
        "cutoff_date": credit.cutoff_date,
        "opening_balance": credit.opening_balance,
        "annual_rate": credit.annual_rate,
        "rate_convention": credit.rate_convention,
        "day_count_convention": credit.day_count_convention,
        "frequency": credit.frequency,
        "term_installments": credit.term_installments,
        "first_due_date": credit.first_due_date,
        "insurance_per_installment": credit.insurance_per_installment,
        "schedule_revision": credit.schedule_revision,
        "closure_date": credit.closure_date,
        "closure_balance": credit.closure_balance,
        "created_at": credit.created_at,
        "updated_at": credit.updated_at,
        "totals": _totals(installments),
        "warnings": warnings,
    }
    if include_installments:
        result["installments"] = [
            {**row.__dict__, "total_amount": row.total_amount}
            for row in installments
        ]
    return result
