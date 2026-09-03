"""
ETL Upload API Endpoints

Excel file ingestion endpoints for the Budget module.
"""

from datetime import date, timedelta
from io import BytesIO
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.orm import Session

import app.crud as crud
from app.schemas import User, BudgetCreate, BudgetLineCreate
from app import get_db
from app.core.auth import get_current_user
from app.api.utils import Exceptions
from app.utils.templates import BudgetTemplates

router = APIRouter()


@router.post("/cost-centers")
async def upload_cost_centers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process a cost centers Excel file.
    Processes the file using the budget templates ETL pipeline.
    """
    # TODO: Implement ETL processing via BudgetTemplates
    return {"message": "Cost centers upload endpoint - implementation pending"}


@router.post("/actual-expenses")
async def upload_actual_expenses(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process LibroAuxiliarCECO.xlsx for actual expenses.
    Maps records against cost centers by codigo_ceco.
    """
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        etl = BudgetTemplates(file_bytes)

        # Fase A: Limpieza
        df = etl.process_actual_expenses()
        total_rows_raw = etl.total_rows_raw

        # Fase B: Mapeo relacional
        etl._map_actual_expenses_relational_data(db)

        # Fase C: Validaciones
        etl._validate_actual_expenses_integrity(db)

        # Fase C (cont.): Reemplazo atómico
        records_deleted = etl._handle_actual_expense_duplicates(db)

        # Fase D: Bulk insert
        inserted_records = etl._bulk_insert_actual_expenses(db, file.filename)

        return {
            "message": "Actual expenses uploaded successfully",
            "records_inserted": len(inserted_records),
            "records_replaced": records_deleted,
            "source_file": file.filename,
            "details": {
                "total_rows_processed": total_rows_raw,
                "rows_filtered": total_rows_raw - len(df),
                "valid_expenses": len(df)
            }
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing actual expenses: {str(e)}"
        )


@router.post("/actual-costs")
async def upload_actual_costs(
    file: UploadFile = File(...),
    excel_total_cost: float = Form(..., description="Total cost from Excel for validation"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process CostosFinal.xlsx for actual costs.

    Process:
    1. Read Excel file
    2. Clean and transform data (document numbers, reference codes)
    3. Map references to id_reference
    4. Infer id_zone from invoice -> order -> customer_trip -> customer -> city -> department
    5. Resolve id_cost_center using (id_zone, id_line, code LIKE '00%')
    6. Validate data integrity (missing references, cost centers, total amount)
    7. Bulk insert into actual_costs table

    Returns:
        JSON with insertion summary
    """
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        # Phase A: Data cleansing
        etl = BudgetTemplates(file_bytes)
        df = etl.process_cost()

        # Phase B: Relational mapping
        df = etl._map_relational_data(db)

        # Phase C: Safety checks
        etl._validate_data_integrity(db, excel_total_cost)

        # Phase D: Detect duplicates and replace if needed
        records_deleted = etl._handle_duplicate_documents(db)

        # Phase E: Bulk insert
        inserted_records = etl._bulk_insert(db, file.filename)

        return {
            "message": "Actual costs uploaded successfully",
            "records_inserted": len(inserted_records),
            "total_amount": sum(r.amount for r in inserted_records),
            "source_file": file.filename,
            "replaced": records_deleted > 0,
            "records_deleted": records_deleted
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing actual costs: {str(e)}"
        )


@router.post("/accounts-receivable")
async def upload_accounts_receivable(
    file: UploadFile = File(...),
    force: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process EstadoCuenta306090.xlsx for accounts receivable.

    Phases: process (cutoff + cleaning) -> map (customers/invoices/aging)
    -> validate (customers, dates, amounts, stale-cutoff guard) -> atomic
    replace by document_number -> snapshot closures -> bulk insert, all in
    a single transaction (only commit happens in phase D).

    Parameters:
    - force: bypass the stale-statement guard when the file cutoff is older
      than the stored one (marks this upload with "forced": true).
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx files are supported",
        )
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        etl = BudgetTemplates(file_bytes)

        # Fase A: Limpieza + parseo de corte (sin DB)
        df = etl.process_accounts_receivable()

        # Fase B: Mapeo relacional (customers/contacts/invoices/aging)
        etl._map_accounts_receivable_relational_data(db)

        # Fase C1: Validaciones bloqueantes + guarda de corte (sin escribir)
        etl._validate_accounts_receivable_integrity(db, force=force)

        # Fase C2: Reemplazo atómico por documento (nullify + delete)
        records_replaced = etl._handle_accounts_receivable_duplicates(db)

        # Fase C3: Cierre por marcaje PAID de deuda desaparecida
        docs = df['document_number'].unique().tolist()
        records_closed = etl._close_settled_accounts_receivable(db, docs)

        # Fase D: Inserción masiva (único commit)
        inserted_records = etl._bulk_insert_accounts_receivable(db, file.filename)

        return {
            "message": "Accounts receivable uploaded successfully",
            "records_inserted": len(inserted_records),
            "records_replaced": records_replaced,
            "records_closed": records_closed,
            "source_file": file.filename,
            "statement_date": str(etl.ar_statement_date),
            "forced": etl.ar_forced,
            "details": {
                "total_rows_raw": etl.total_rows_raw,
                "rows_excluded_subtotals": etl.ar_rows_excluded_subtotals,
                "total_outstanding_balance": round(
                    float(df['Valor Total'].sum()), 2
                ),
                "legacy_debt_records": etl.ar_legacy_debt_records,
                "unique_customers": int(df['id_customer'].nunique()),
                "contact_fallback_resolved": etl.ar_contact_fallback_resolved,
            },
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing accounts receivable: {str(e)}",
        )


@router.post("/payment-ledger")
async def upload_payment_ledger(
    file: UploadFile = File(...),
    include_initial_balances: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process Recibos.xlsx for the payment ledger (cash-flow ETL).

    Phases: process -> map -> validate -> dedupe (atomic replace by
    receipt_number) -> bulk insert, all in a single transaction.
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx files are supported",
        )
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        # Fase A: Limpieza y clasificación por naturaleza
        etl = BudgetTemplates(file_bytes)
        df = etl.process_payment_ledger(include_initial_balances=include_initial_balances)

        # Fase B: Imputación de documento afectado y cliente opcional
        etl._map_payment_ledger_relational_data(db)

        # Fase C: Validaciones y reemplazo atómico por recibo
        etl._validate_payment_ledger_integrity(db)
        records_deleted = etl._handle_payment_ledger_duplicates(db)

        # Fase D: Inserción masiva (commit)
        inserted_records = etl._bulk_insert_payment_ledger(db, file.filename)

        cash = df[df['transaction_nature'] == 'CASH']
        non_cash = df[df['transaction_nature'] == 'NON_CASH_ADJUSTMENT']
        cash_in = cash[cash['cash_flow'] == 'in']
        cash_out = cash[cash['cash_flow'] == 'out']

        return {
            "message": "Payment ledger uploaded successfully",
            "records_inserted": len(inserted_records),
            "records_replaced": records_deleted,
            "source_file": file.filename,
            "include_initial_balances": include_initial_balances,
            "details": {
                "total_rows_processed": etl.total_rows_raw,
                "rows_excluded_totals": etl.rows_excluded_totals,
                "rows_excluded_documents": etl.rows_excluded_documents,
                "rows_excluded_initial_balances": etl.rows_excluded_initial_balances,
                "rows_skipped_null": etl.rows_skipped_null,
                "cash_records": len(cash),
                "non_cash_records": len(non_cash),
                "cash_in_count": len(cash_in),
                "cash_out_count": len(cash_out),
                "total_cash_in": round(float(cash_in['payment_amount'].sum()), 2),
                "total_cash_out": round(float(cash_out['payment_amount'].sum()), 2),
                "net_liquidity": round(float(cash['payment_amount'].sum()), 2),
                "total_non_cash_adjustments": round(float(non_cash['payment_amount'].sum()), 2),
                "rows_with_document_candidate": etl.rows_with_document_candidate,
                "invoices_imputed": etl.invoices_imputed,
                "documents_not_imputed": etl.documents_not_imputed,
            },
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing payment ledger: {str(e)}",
        )


@router.post("/budget-plan-income")
async def upload_budget_plan_income(
    budget_name: str = Form(...),
    budget_year: int = Form(...),
    budget_period: str = Form(...),
    id_department: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process income budget plan Excel template.
    Creates a draft budget and bulk inserts budget lines.
    """
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    budget_data = BudgetCreate(
        budget_name=budget_name,
        budget_year=budget_year,
        budget_period=budget_period,
        id_department=id_department,
        status="draft",
    )
    new_budget = crud.create_budget(db, budget_data)

    try:
        etl = BudgetTemplates(file_bytes)
        df = etl.process_budget_plan_income()
        records = etl.dataframe_to_records()

        missing_cost_centers = []
        budget_lines_data: List[Dict[str, Any]] = []

        for record in records:
            cc_code = record.get("id_cost_center_code")
            cc = crud.get_cost_center_by_code(db, cc_code)
            if not cc:
                missing_cost_centers.append(cc_code)
                continue

            coll_short = record.get("short_collection_name")
            coll = crud.get_collection_by_short_name(db, coll_short)
            id_collection = coll.id_collection if coll else None

            budget_date = record.get("budget_date")
            if isinstance(budget_date, str):
                from datetime import datetime
                budget_date = datetime.strptime(budget_date, "%Y-%m-%d").date()

            id_line = cc.id_line
            payment_date = budget_date

            if id_line:
                rules = crud.get_line_payment_rules_by_line(db, id_line)
                if rules:
                    if len(rules) == 1 and rules[0].payment_days == 0:
                        payment_date = budget_date
                    else:
                        for rule in rules:
                            rule_payment_date = budget_date + timedelta(days=rule.payment_days)
                            partial_amount = record.get("projected_amount", 0) * rule.payment_pct
                            budget_lines_data.append({
                                "id_budget": new_budget.id_budget,
                                "id_cost_center": cc.id_cost_center,
                                "line_type": "income",
                                "budget_date": budget_date,
                                "payment_date": rule_payment_date,
                                "id_collection": id_collection,
                                "projected_amount": partial_amount,
                                "description": record.get("description"),
                                "behavior_type": "fixed",
                            })
                        continue

            budget_lines_data.append({
                "id_budget": new_budget.id_budget,
                "id_cost_center": cc.id_cost_center,
                "line_type": "income",
                "budget_date": budget_date,
                "payment_date": payment_date,
                "id_collection": id_collection,
                "projected_amount": record.get("projected_amount", 0),
                "description": record.get("description"),
                "behavior_type": "fixed",
            })

        if missing_cost_centers:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cost centers not found: {missing_cost_centers}",
            )

        if budget_lines_data:
            lines_to_create = [BudgetLineCreate(**data) for data in budget_lines_data]
            crud.create_budget_lines_bulk(db, lines_to_create)

        return {
            "message": "Income budget plan uploaded successfully",
            "id_budget": new_budget.id_budget,
            "budget_lines_count": len(budget_lines_data),
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing income budget plan: {str(e)}",
        )


@router.post("/budget-plan-expense")
async def upload_budget_plan_expense(
    budget_name: str = Form(...),
    budget_year: int = Form(...),
    budget_period: str = Form(...),
    id_department: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process expense budget plan Excel template.
    Creates a draft budget and bulk inserts budget lines.
    """
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    budget_data = BudgetCreate(
        budget_name=budget_name,
        budget_year=budget_year,
        budget_period=budget_period,
        id_department=id_department,
        status="draft",
    )
    new_budget = crud.create_budget(db, budget_data)

    try:
        etl = BudgetTemplates(file_bytes)
        df = etl.process_budget_plan_expense()
        records = etl.dataframe_to_records()

        missing_cost_centers = []
        budget_lines_data: List[Dict[str, Any]] = []

        for record in records:
            cc_code = record.get("id_cost_center_code")
            cc = crud.get_cost_center_by_code(db, cc_code)
            if not cc:
                missing_cost_centers.append(cc_code)
                continue

            coll_short = record.get("short_collection_name")
            coll = crud.get_collection_by_short_name(db, coll_short)
            id_collection = coll.id_collection if coll else None

            budget_date = record.get("budget_date")
            if isinstance(budget_date, str):
                from datetime import datetime
                budget_date = datetime.strptime(budget_date, "%Y-%m-%d").date()

            payment_date = record.get("payment_date")
            if isinstance(payment_date, str):
                from datetime import datetime
                payment_date = datetime.strptime(payment_date, "%Y-%m-%d").date()

            behavior_type = record.get("behavior_type", "fixed")
            projected_amount = record.get("projected_amount", 0)
            variable_rate = record.get("variable_rate")

            if behavior_type != "fixed" and variable_rate is not None:
                projected_amount = 0

            budget_lines_data.append({
                "id_budget": new_budget.id_budget,
                "id_cost_center": cc.id_cost_center,
                "line_type": "expense",
                "budget_date": budget_date,
                "payment_date": payment_date,
                "id_collection": id_collection,
                "projected_amount": projected_amount,
                "description": record.get("description"),
                "behavior_type": behavior_type,
                "variable_rate": variable_rate,
            })

        if missing_cost_centers:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cost centers not found: {missing_cost_centers}",
            )

        if budget_lines_data:
            lines_to_create = [BudgetLineCreate(**data) for data in budget_lines_data]
            crud.create_budget_lines_bulk(db, lines_to_create)

        return {
            "message": "Expense budget plan uploaded successfully",
            "id_budget": new_budget.id_budget,
            "budget_lines_count": len(budget_lines_data),
        }

    except HTTPException as e:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing expense budget plan: {str(e)}",
        )
