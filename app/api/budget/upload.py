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
    # TODO: Implement ETL processing via BudgetTemplates
    return {"message": "Actual expenses upload endpoint - implementation pending"}


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process EstadoCuenta306090.xlsx for accounts receivable.
    Applies skiprows=3 for header omission and structures the DataFrame.
    """
    # TODO: Implement ETL processing via BudgetTemplates
    return {"message": "Accounts receivable upload endpoint - implementation pending"}


@router.post("/payment-ledger")
async def upload_payment_ledger(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process RecibosDePago.xlsx for payment ledger.
    Maps records against account receivables and collections.
    """
    # TODO: Implement ETL processing via BudgetTemplates
    return {"message": "Payment ledger upload endpoint - implementation pending"}


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
