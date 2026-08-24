"""
ETL Upload API Endpoints

Excel file ingestion endpoints for the Budget module.
"""

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session

from app.schemas import User
from app import get_db
from app.core.auth import get_current_user

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process CostosFinal.xlsx for actual costs.
    Maps records against cost centers by codigo_ceco.
    """
    # TODO: Implement ETL processing via BudgetTemplates
    return {"message": "Actual costs upload endpoint - implementation pending"}


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
