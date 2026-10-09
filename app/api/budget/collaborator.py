"""
Collaborator (NÃ³mina) API Endpoints (BE-S11-COLLABORATORS, backend.02_21 Â§9)

Three routers mounted by app/api/budget/__init__.py:

- router               â†’ /budget/collaborator        (maestro + import +
                       salary-plan + terminate + breakdown + provisions +
                       recalculate)
- labor_params_router  â†’ /budget/labor-params        (catÃ¡logo vigente +
                       arl_rates; GET/PUT admin)
- cost_components_router â†’ /budget/cost-components   (catÃ¡logo lectura)

Authorization (D-S11-7, OQ-BE-2 resolved pragmatically):
COLLAB_VIEW_ROLES / COLLAB_EDIT_ROLES are comma-separated role_name
allow-lists in settings (parsed exactly like BACKEND_CORS_ORIGINS). An
EMPTY list means "not configured yet" â†’ any authenticated user passes â€”
the same JWT-only posture every other budget endpoint has today, so the
feature never 403s an integration that worked before the lists exist
(documented per module, OQ-BE-2 will set the real names in .env).
Master reads NEVER hard-fail without VIEW: the salary arrives as
``salary: null`` + ``salary_masked: true`` (D-S11-7/BR-14, AC-SEG-1);
the endpoints that EXPOSE computed money (breakdown/provisions/params
GET) gate 403 instead (Â§9 Roles).

T-05: every mutation runs validations, master upserts, plans and the
motor, and commits ONCE at the end. Missing vigencia for the affected
months raises MissingLaborParametersError â†’ structured 400 (R-05/BR-03,
AC-CFG-1: zero lines â€” the transaction rolled back).
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, UploadFile, status,
)
from sqlalchemy.orm import Session

import app.crud as crud
from app import get_db
from app.api.utils import Exceptions
from app.core.auth import get_current_user
from app.schemas import (
    BreakdownOut,
    CollaboratorCreate, CollaboratorUpdate, CollaboratorOut,
    CollaboratorListResponse, CollaboratorImportResult,
    CostComponentOut,
    LaborParameterUpsert, LaborParamsResponse,
    ProvisionsOut, ProvisionBalanceOut,
    MaterializationStatusOut,
    RecalculateRequest, RecalculateResult,
    SalaryPlanCreate, SalaryPlanOut,
    TerminateRequest,
    User,
)
from app.services.laborCostEngine import (
    CostCatalogIncompleteError, LaborCostEngine, MissingLaborParametersError,
)
from app.settings import settings
from app.utils.templates import BudgetTemplates

router = APIRouter()
labor_params_router = APIRouter()
cost_components_router = APIRouter()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Role gates (D-S11-7 / OQ-BE-2)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _role_name_of(current_user: User) -> Optional[str]:
    """Defensive read of the joined role (same pattern as
    planning.require_target_admin)."""
    return getattr(getattr(current_user, "role", None), "role_name", None)


def _in_allow_list(roles: Optional[List[str]], current_user: User) -> bool:
    """settings list parsed like BACKEND_CORS_ORIGINS; empty/absent list
    = not configured = any authenticated user (documented default)."""
    if not roles:
        return True
    return _role_name_of(current_user) in roles


def has_view_access(current_user: User) -> bool:
    return _in_allow_list(settings.COLLAB_VIEW_ROLES, current_user)


def require_collab_view(
    current_user: User = Depends(get_current_user),
) -> User:
    """403 without a readable salary (Â§9: breakdown/salary-plan/params
    GET â†’ COLLAB_VIEW_ROLES)."""
    if not has_view_access(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your role is not in COLLAB_VIEW_ROLES: payroll "
                "breakdowns, provisions and parameters are confidential "
                "(Ley 1581/2012, D-S11-7)"
            ),
        )
    return current_user


def require_collab_edit(
    current_user: User = Depends(get_current_user),
) -> User:
    """403 for mutations (import/create/update/terminate/recalculate/
    salary-plan/params-PUT â†’ COLLAB_EDIT_ROLES, Â§9)."""
    if not _in_allow_list(settings.COLLAB_EDIT_ROLES, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your role is not in COLLAB_EDIT_ROLES: you cannot "
                "modify payroll data (D-S11-7)"
            ),
        )
    return current_user


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Serialization with salary masking (BR-14)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _collaborator_out(
    db: Session, collab, can_view: bool
) -> CollaboratorOut:
    """Master + denormalized CURRENT plan (open valid_to NULL, latest
    valid_from â€” never the historical ones). Without VIEW the four
    economic fields answer null + salary_masked=true (D-S11-7)."""
    plan = crud.get_open_salary_plan(db, collab.id_collaborator)
    cost_center_name = None
    if collab.cost_center is not None:
        cost_center_name = collab.cost_center.cost_center_name

    out = CollaboratorOut(
        id_collaborator=collab.id_collaborator,
        doc_type=collab.doc_type,
        doc_value=collab.doc_value,
        full_name=collab.full_name,
        id_cost_center=collab.id_cost_center,
        contract_type=collab.contract_type,
        status=collab.status,
        hire_date=collab.hire_date,
        termination_date=collab.termination_date,
        risk_class=collab.risk_class,
        id_collection=collab.id_collection,
        notes=collab.notes,
        created_at=collab.created_at,
        updated_at=collab.updated_at,
        cost_center_name=cost_center_name,
    )
    if can_view and plan is not None:
        out.salary = Decimal(plan.salary)
        out.allowance_salary = Decimal(plan.allowance_salary or 0)
        out.allowance_non_salary = Decimal(plan.allowance_non_salary or 0)
        out.is_integral = bool(plan.is_integral)
        out.valid_from = plan.valid_from
    if not can_view:
        out.salary_masked = True
    return out


def _engine_http_error(exc: Exception) -> HTTPException:
    """R-05/BR-03 + catalog: controlled 400 with the missing-vigencia /
    missing-catalog message (NEVER a 500)."""
    if isinstance(exc, MissingLaborParametersError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "vigencia": exc.vigencia},
        )
    if isinstance(exc, CostCatalogIncompleteError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Error processing payroll: {str(exc)}",
    )


def _run_window(
    engine: LaborCostEngine, collab, load_month: date
) -> Any:
    """Motor run over the D-S11-8 window of one collaborator (flush
    only â€” the caller commits)."""
    start_first, end_last = engine.resolve_window(collab, load_month)
    return engine.run_projection(collab, start_first, end_last)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Import (plantilla de nÃ³mina) â€” Â§6/Â§9, R-06/R-07/R-09
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/import", response_model=CollaboratorImportResult)
async def collaborator_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """POST /budget/collaborator/import â€” "Solicitud Presupuesto
    NÃ³mina/Colaboradores.xlsx" (Â§6, A-13). ALL-OR-NOTHING (R-06/T-05):
    any invalid cell (ETL) or unknown cost center raises 400
    {message, invalid_rows:[{excel_row, motivo}]} with ZERO persisted
    rows (nothing was flushed before the rejection, AC-PLT-1).

    Upsert by doc_value (R-07/BR-05): inexistente â‡’ alta maestro+plan
    (created); distinto â‡’ plan nuevo/cierre de vigencia (updated);
    idÃ©ntico â‡’ no-op (no_change). The file NEVER carries totals â€”
    the motor derives everything (R-08/BR-01).

    R-09/BR-15: on success the motor runs for every collaborator of the
    file over the D-S11-8 window (load month — pulled back to the
    oldest vigencia of the scenario year, e.g. an alta whose hire_date
    opened in January, or extended back to the termination month of the
    same year when the file closes a contract — .. 31/12 of the active
    scenario year, §5.5) and replaces its own budget_lines idempotently
    (R-13) — then ONE commit (T-05).
    """
    contents = await file.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded payroll file is empty",
        )

    etl = BudgetTemplates(BytesIO(contents))
    try:
        # 400 structured (missing columns / invalid cells) before any
        # DB write.
        etl.process_budget_plan_collaborators()
        records = etl.dataframe_to_records()

        # ---- Phase 1: CECO resolution (unknown -> invalid_rows, Â§6) ----
        invalid_rows: List[Dict[str, Any]] = []
        cc_cache: Dict[str, Any] = {}
        for rec in records:
            code = rec.get("id_cost_center_code")
            if code not in cc_cache:
                cc_cache[code] = crud.get_cost_center_by_code(db, code)
            if cc_cache[code] is None:
                invalid_rows.append({
                    "excel_row": rec.get("excel_row"),
                    "motivo": f"Centro de Costo desconocido: '{code}'",
                })
        if invalid_rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": (
                        f"Payroll file has {len(invalid_rows)} row(s) "
                        "with unresolvable data (all-or-nothing, R-06)"
                    ),
                    "invalid_rows": invalid_rows[:20],
                },
            )

        # ---- Phase 2: master + plan upserts (flush only, T-05) ----
        today = date.today()
        # Â§6: Fecha de Ingreso default = primer dÃ­a de la ventana (the
        # load window starts at the load month).
        default_hire = date(today.year, today.month, 1)

        created = updated = no_change = 0
        touched: Dict[int, Any] = {}  # id_collaborator -> model (unique)

        for rec in records:
            doc_value = rec.get("doc_value")
            cc = cc_cache[rec.get("id_cost_center_code")]

            # Temporada tolerant (purchase A-01 parity): unknown or
            # blank -> id_collection untouched on update / NULL on alta.
            id_collection = None
            short_name = (rec.get("short_collection_name") or "").strip()
            if short_name:
                coll = crud.get_collection_by_short_name(db, short_name)
                id_collection = coll.id_collection if coll else None

            contract_type = rec.get("contract_type")
            termination_date = rec.get("termination_date")
            status_value = (
                "terminated"
                if termination_date is not None and termination_date <= today
                else "active"
            )

            collab = crud.get_collaborator_by_doc_value(db, doc_value)
            is_alta = collab is None
            if collab is None:
                collab = crud.create_collaborator(db, {
                    "doc_type": rec.get("doc_type") or "CC",
                    "doc_value": doc_value,
                    "full_name": rec.get("full_name"),
                    "id_cost_center": cc.id_cost_center,
                    "contract_type": contract_type,
                    "status": status_value,
                    "hire_date": rec.get("hire_date") or default_hire,
                    "termination_date": termination_date,
                    "risk_class": rec.get("risk_class"),
                    "id_collection": id_collection,
                    "notes": rec.get("notes"),
                })
            else:
                fields: Dict[str, Any] = {
                    "full_name": rec.get("full_name"),
                    "id_cost_center": cc.id_cost_center,
                    "contract_type": contract_type,
                }
                if rec.get("doc_type"):
                    fields["doc_type"] = rec["doc_type"]
                if rec.get("hire_date"):
                    fields["hire_date"] = rec["hire_date"]
                if rec.get("risk_class"):
                    fields["risk_class"] = rec["risk_class"]
                if short_name:
                    fields["id_collection"] = id_collection
                if rec.get("notes"):
                    fields["notes"] = rec["notes"]
                if termination_date is not None:
                    fields["termination_date"] = termination_date
                    fields["status"] = status_value
                crud.update_collaborator_master(db, collab, fields)

            # is_integral is NOT a payroll-template column (Â§6): None
            # keeps the open plan's flag (or False on alta â€” the plan
            # helper below resolves it).
            open_plan = crud.get_open_salary_plan(db, collab.id_collaborator)
            is_integral = (
                bool(open_plan.is_integral) if open_plan is not None else False
            )

            # Blank "Aumento Salarial": on ALTA the first vigencia starts
            # at the hire date (otherwise the motor has no plan for the
            # months before the import day and causes from today only);
            # re-imports of existing collaborators keep today so the
            # same-values no-op guard stays idempotent (AC-PLT-2).
            default_vigencia = (
                (rec.get("hire_date") or default_hire) if is_alta else today
            )

            action = crud.apply_salary_plan(
                db, collab,
                salary=Decimal(str(rec.get("salary"))),
                allowance_salary=Decimal(str(rec.get("allowance_salary") or 0)),
                allowance_non_salary=Decimal(str(
                    rec.get("allowance_non_salary") or 0
                )),
                is_integral=is_integral,
                valid_from=rec.get("valid_from") or default_vigencia,
            )
            if action == "created":
                created += 1
            elif action == "updated":
                updated += 1
            else:
                no_change += 1
            touched[collab.id_collaborator] = collab

        # ---- Phase 3: motor (R-09/BR-15) for every touched row ----
        engine = LaborCostEngine(db)
        generated_lines = 0
        warnings: List[str] = []
        for collab in touched.values():
            result = _run_window(engine, collab, today)
            generated_lines += result.created_lines
            warnings.extend(result.warnings)

        # ---- The ONLY commit of the whole operation (T-05) ----
        db.commit()

        return CollaboratorImportResult(
            imported=len(records),
            created=created,
            updated=updated,
            no_change=no_change,
            generated_lines=generated_lines,
            warnings=warnings,
        )

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        # R-05/BR-03 (AC-CFG-1) and phase-3 seed guard (AC-DEP-1): the
        # ENTIRE import rolls back â€” masters, plans and lines (T-05).
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error importing payroll file: {str(e)}",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Recalculate â€” Â§9 (R-13 idempotent replacement of the year)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/recalculate", response_model=RecalculateResult)
def collaborator_recalculate(
    payload: RecalculateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """Re-runs the motor over the months of the scenario year of
    ``month`` (Â§7/R-13, "cambios de parÃ¡metros recalculan solo meses
    â‰¥ nueva vigencia" applies per seat year: only the months of the
    affected year are deleted+regenerated). Optional scope by
    id_collaborator or id_cost_center; no scope = all collaborators.
    Motor-owned rows only â€” manual/other-template/real rows never
    touched (BR-09/BR-13)."""
    try:
        year = int(payload.month.split("-")[0])

        if payload.id_collaborator is not None:
            collab = crud.get_collaborator_by_id(
                db, payload.id_collaborator
            )
            if collab is None:
                Exceptions.register_not_found(
                    "Collaborator", payload.id_collaborator
                )
            targets = [collab]
        elif payload.id_cost_center is not None:
            _, targets = crud.query_collaborators(
                db, id_cost_center=payload.id_cost_center, page=1,
                size=1_000_000,
            )
        else:
            _, targets = crud.query_collaborators(page=1, size=1_000_000, db=db)

        engine = LaborCostEngine(db)
        created = deleted = 0
        warnings: List[str] = []
        for collab in targets:
            result = engine.run_projection(
                collab, date(year, 1, 1), date(year, 12, 31)
            )
            created += result.created_lines
            deleted += result.deleted_lines
            warnings.extend(result.warnings)

        db.commit()
        return RecalculateResult(
            replaced_lines=deleted,
            created_lines=created,
            collaborators=len(targets),
            warnings=warnings,
        )

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error recalculating payroll: {str(e)}",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Master CRUD â€” Â§9
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("", response_model=CollaboratorListResponse)
def list_collaborators(
    q: Optional[str] = Query(
        None, description="Search by full_name / doc_value (ilike)"
    ),
    id_cost_center: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None, description="active | terminated"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GET /budget/collaborator â†’ {total, items[]}. No 403 without
    VIEW â€” the list simply arrives with masked salaries (Â§9/D-S11-7)."""
    can_view = has_view_access(current_user)
    total, rows = crud.query_collaborators(
        db, q=q, id_cost_center=id_cost_center, status=status,
        page=page, size=size,
    )
    return CollaboratorListResponse(
        total=total,
        items=[_collaborator_out(db, c, can_view) for c in rows],
    )


@router.post("", response_model=CollaboratorOut,
             status_code=status.HTTP_201_CREATED)
def create_collaborator(
    payload: CollaboratorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """Manual alta (POST): maestro + primera vigencia salarial.
    doc_value duplicated â†’ 409; unknown CECO/collection â†’ 404; the
    motor materializes the D-S11-8 window in the SAME commit (R-09)."""
    try:
        if crud.get_collaborator_by_doc_value(db, payload.doc_value):
            Exceptions.register_already_registered(
                "Collaborator", payload.doc_value
            )
        if crud.get_cost_center_by_id(db, payload.id_cost_center) is None:
            Exceptions.register_not_found(
                "CostCenter", payload.id_cost_center
            )
        if payload.id_collection is not None:
            if crud.get_collection_by_id(db, payload.id_collection) is None:
                Exceptions.register_not_found(
                    "Collection", payload.id_collection
                )

        terminated = (
            payload.termination_date is not None
            and payload.termination_date <= date.today()
        )
        collab = crud.create_collaborator(db, {
            "doc_type": payload.doc_type,
            "doc_value": payload.doc_value,
            "full_name": payload.full_name,
            "id_cost_center": payload.id_cost_center,
            "contract_type": payload.contract_type,
            "status": "terminated" if terminated else "active",
            "hire_date": payload.hire_date,
            "termination_date": payload.termination_date,
            "risk_class": payload.risk_class,
            "id_collection": payload.id_collection,
            "notes": payload.notes,
        })

        if payload.salary is not None:
            # Manual alta: the first vigencia starts at the hire date so
            # the motor causes the full months from ingreso onwards
            # (clamping to today silently zeroed Jan..import-month).
            valid_from = payload.valid_from or payload.hire_date
            crud.apply_salary_plan(
                db, collab,
                salary=payload.salary,
                allowance_salary=payload.allowance_salary,
                allowance_non_salary=payload.allowance_non_salary,
                is_integral=payload.is_integral,
                valid_from=valid_from,
                force_new_vigencia=True,
            )

            engine = LaborCostEngine(db)
            _run_window(engine, collab, date.today())

        db.commit()
        db.refresh(collab)
        return _collaborator_out(db, collab, has_view_access(current_user))

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating collaborator: {str(e)}",
        )


@router.get("/materialization-status", response_model=MaterializationStatusOut)
def materialization_status(
    year: Optional[int] = Query(None, ge=2000, le=2199),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """BE-S11 enmienda (Opcion A): conteo de materializacion para el banner
    del editor de escenario. SOLO conteos agregados: cero salarios/nombres/
    montos cruzan este endpoint, por eso la puerta es auth simple (no
    COLLAB_VIEW_ROLES — D-S11-7 protege datos economicos, no advertencias).

    needs_materialization = escenario activo del ano + colaboradores con plan
    abierto + CERO lineas del motor en ese escenario."""
    target_year = year or date.today().year
    scenario = crud.get_active_budget_for_year(db, target_year)
    with_plan = crud.count_collaborators_with_open_plan(db)
    lines = (
        crud.count_engine_lines_for_budget(db, scenario.id_budget)
        if scenario is not None
        else 0
    )
    return MaterializationStatusOut(
        year=target_year,
        scenario_id_budget=(
            scenario.id_budget if scenario is not None else None
        ),
        active_collaborators=crud.count_active_collaborators(db),
        collaborators_with_open_plan=with_plan,
        payroll_lines_in_scenario=lines,
        needs_materialization=bool(
            scenario is not None and with_plan > 0 and lines == 0
        ),
    )


@router.get("/{id_collaborator}", response_model=CollaboratorOut)
def get_collaborator(
    id_collaborator: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One master row (masked without VIEW, Â§9/D-S11-7)."""
    collab = crud.get_collaborator_by_id(db, id_collaborator)
    if collab is None:
        Exceptions.register_not_found("Collaborator", id_collaborator)
    out = _collaborator_out(db, collab, has_view_access(current_user))
    if out is not None and not out.salary_masked:
        # detail-only: FE-S15 history table (N+1 avoided on lists)
        out.salary_plans = [
            SalaryPlanOut.model_validate(p)
            for p in crud.get_salary_plans(db, id_collaborator)
        ]
    return out


@router.put("/{id_collaborator}", response_model=CollaboratorOut)
def update_collaborator(
    id_collaborator: int,
    payload: CollaboratorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """PUT campos maestro (NO salario â€” Â§9; the salary route is
    POST /{id}/salary-plan which appends a vigencia, BR-02). Changing
    contract_type/CECO/risk re-runs the motor over the projection
    window; the months before the load window keep their history
    (A-10)."""
    try:
        collab = crud.get_collaborator_by_id(db, id_collaborator)
        if collab is None:
            Exceptions.register_not_found("Collaborator", id_collaborator)

        fields = payload.model_dump(exclude_unset=True)
        fields = {k: v for k, v in fields.items() if v is not None}

        new_doc = fields.get("doc_value")
        if new_doc and new_doc != collab.doc_value:
            if crud.get_collaborator_by_doc_value(db, new_doc):
                Exceptions.register_already_registered(
                    "Collaborator", new_doc
                )
        if "id_cost_center" in fields and \
                crud.get_cost_center_by_id(db, fields["id_cost_center"]) is None:
            Exceptions.register_not_found(
                "CostCenter", fields["id_cost_center"]
            )
        if "id_collection" in fields and \
                crud.get_collection_by_id(db, fields["id_collection"]) is None:
            Exceptions.register_not_found(
                "Collection", fields["id_collection"]
            )

        crud.update_collaborator_master(db, collab, fields)

        engine = LaborCostEngine(db)
        _run_window(engine, collab, date.today())

        db.commit()
        db.refresh(collab)
        return _collaborator_out(db, collab, has_view_access(current_user))

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating collaborator: {str(e)}",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Salary plan â€” Â§9 (BR-02/BR-COLLAB-02)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/{id_collaborator}/salary-plan", response_model=SalaryPlanOut,
             status_code=status.HTTP_201_CREATED)
def create_salary_plan(
    id_collaborator: int,
    payload: SalaryPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """New salary vigencia: CLOSES the open plan
    (valid_to = valid_from - 1) and appends â€” closed history is never
    edited (BR-COLLAB-02/R-01). The motor then reprojects the affected
    window from the load month (A-10: no retroactive rewrites)."""
    try:
        collab = crud.get_collaborator_by_id(db, id_collaborator)
        if collab is None:
            Exceptions.register_not_found("Collaborator", id_collaborator)

        crud.apply_salary_plan(
            db, collab,
            salary=payload.salary,
            allowance_salary=payload.allowance_salary,
            allowance_non_salary=payload.allowance_non_salary,
            is_integral=payload.is_integral,
            valid_from=payload.valid_from,
            force_new_vigencia=True,
        )

        engine = LaborCostEngine(db)
        _run_window(engine, collab, date.today())

        db.commit()
        plan = crud.get_open_salary_plan(db, id_collaborator)
        return SalaryPlanOut.model_validate(plan)

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating salary plan: {str(e)}",
        )


@router.post("/{id_collaborator}/terminate", response_model=CollaboratorOut)
def terminate_collaborator(
    id_collaborator: int,
    payload: TerminateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """POST /{id}/terminate â†’ status terminated + LIQ seats (Â§5.5,
    BR-LIQ-01): settlement = saldo PRIMA + CESANTIAS + INTERESES +
    prorrateo CAJA of the termination month, payment_date =
    termination_date, source_engine = collaborator_liquidation. Months
    beyond the term produce zero seats (R-11) and stale motor rows are
    cleaned by the R-13 replacement of the run."""
    try:
        collab = crud.get_collaborator_by_id(db, id_collaborator)
        if collab is None:
            Exceptions.register_not_found("Collaborator", id_collaborator)
        if payload.termination_date < collab.hire_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "termination_date cannot precede hire_date "
                    f"({collab.hire_date.isoformat()})"
                ),
            )

        crud.set_collaborator_termination(
            db, collab, payload.termination_date
        )

        engine = LaborCostEngine(db)
        # Run from the TERMINATION month (retro inside the same year is
        # auto-extended by run_projection): months after the term are
        # cleaned with zero regeneration (R-11/R-13).
        start_first, end_last = engine.resolve_window(
            collab, date(payload.termination_date.year,
                         payload.termination_date.month, 1)
        )
        engine.run_projection(collab, start_first, end_last)

        db.commit()
        db.refresh(collab)
        return _collaborator_out(db, collab, has_view_access(current_user))

    except HTTPException:
        db.rollback()
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        db.rollback()
        raise _engine_http_error(e)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error terminating collaborator: {str(e)}",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Read derivations â€” Â§9 (VIEW-gated money)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/{id_collaborator}/breakdown", response_model=BreakdownOut)
def get_breakdown(
    id_collaborator: int,
    month: str = Query(
        ..., pattern=r"^\d{4}-\d{2}$",
        description="Seat month YYYY-MM (e.g. 2026-09)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_view),
):
    """Motor seats of one month, pure READ derivation (nothing is
    persisted â€” same in-memory path the motor would write):
    {month, components[{code,name,layer,amount,payment_date,kind}],
    total_caja, total_provision, params_vigencia}. AC-CALC-4 shape: no
    PRIMA/CESANTIAS/INTERESES payment seat outside the legal months;
    CAJA seats pay on dia_pago_salario. R-05: a month of a vigencia
    without parameters â†’ 400 (AC-CFG-1)."""
    try:
        collab = crud.get_collaborator_by_id(db, id_collaborator)
        if collab is None:
            Exceptions.register_not_found("Collaborator", id_collaborator)
        year, mon = (int(p) for p in month.split("-"))
        if not 1 <= mon <= 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="month must be a valid calendar month (YYYY-MM)",
            )
        engine = LaborCostEngine(db)
        return BreakdownOut(**engine.breakdown(collab, date(year, mon, 1)))
    except HTTPException:
        raise
    except (MissingLaborParametersError, CostCatalogIncompleteError) as e:
        raise _engine_http_error(e)


@router.get("/{id_collaborator}/provisions", response_model=ProvisionsOut)
def get_provisions(
    id_collaborator: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_view),
):
    """Â§9: {balances:[{component_code, accrued, paid, balance}]} from
    the causacion ledger (D-S11-3): balance = Î£acruado âˆ’ Î£pagado per
    component. ``paid`` is engine-set only (there is no real payment in
    the CRM, A-05)."""
    collab = crud.get_collaborator_by_id(db, id_collaborator)
    if collab is None:
        Exceptions.register_not_found("Collaborator", id_collaborator)
    balances = [
        ProvisionBalanceOut(
            component_code=code, accrued=accrued, paid=paid,
            balance=accrued - paid,
        )
        for code, accrued, paid in crud.get_provision_balances(
            db, id_collaborator
        )
    ]
    return ProvisionsOut(id_collaborator=id_collaborator, balances=balances)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Labor parameters â€” Â§4.3/Â§4.4, Â§9
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@labor_params_router.get("", response_model=LaborParamsResponse)
def get_labor_params(
    vigencia: int = Query(..., ge=2000, le=2100,
                          description="Annual vigencia (e.g. 2026)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_view),
):
    """GET /budget/labor-params?vigencia=2026: key/value catalog + the
    arl_rates of that vigencia (Â§9). An unknown vigencia is NOT an
    error here (empty catalogs): R-05 fires where the MOTOR needs the
    parameters (breakdown/import/recalculate), so admins can always
    read-before-write."""
    rows = crud.get_labor_parameters(db, vigencia)
    arl = crud.get_labor_arl_rates(db, vigencia)
    return LaborParamsResponse(
        vigencia=vigencia,
        params={row.key: row.value for row in rows},
        arl_rates={cls: rate for cls, rate in arl.items()},
    )


@labor_params_router.put("", response_model=LaborParamsResponse)
def put_labor_params(
    payload: LaborParameterUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_collab_edit),
):
    """PUT /budget/labor-params {vigencia, values:{key:value},
    arl_rates?:{I..V:rate}}: upsert per key (A-11 editable, A-02 zero
    hardcode; NFR-03: parameters evolve through THIS audited endpoint,
    never DELETE of histories â€” old vigencias stay for reproducibility).
    Rate values arrive as Decimal-strings (D-S11-4)."""
    try:
        if not payload.values and not payload.arl_rates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="values and/or arl_rates must be provided",
            )
        for key, value in payload.values.items():
            # Structural only (A-11 free-form keys stay open; the motor
            # validates what it needs when it needs it â€” R-05).
            str(value).strip()
        crud.upsert_labor_parameters(db, payload.vigencia, payload.values)
        if payload.arl_rates:
            crud.upsert_labor_arl_rates(db, payload.vigencia, {
                cls: Decimal(str(rate))
                for cls, rate in payload.arl_rates.items()
            })
        db.commit()

        rows = crud.get_labor_parameters(db, payload.vigencia)
        arl = crud.get_labor_arl_rates(db, payload.vigencia)
        return LaborParamsResponse(
            vigencia=payload.vigencia,
            params={row.key: row.value for row in rows},
            arl_rates={cls: rate for cls, rate in arl.items()},
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating labor parameters: {str(e)}",
        )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Cost components catalog â€” Â§4.5, Â§9
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@cost_components_router.get("", response_model=List[CostComponentOut])
def get_cost_components_api(
    include_inactive: bool = Query(
        False,
        description="Admin/UI detail: also list the extralegales seeded "
                    "is_active=False (A-11/R-12)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GET /budget/cost-components: read-only catalog (seeded, phase 3
    Â§4.8). Default hides the inactive components (FE never renders
    them)."""
    return crud.get_cost_components(db, active_only=not include_inactive)
