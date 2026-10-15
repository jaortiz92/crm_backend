"""Tax planning catalog and budget simulation API."""
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app import get_db
from app.core.auth import get_current_user
from app.schemas import User
from app.schemas.budget import (TaxProfile, TaxProfileCreate, TaxRate, TaxRateCreate, TaxCalendar, TaxCalendarCreate,
    BudgetTaxAssumption, BudgetTaxAssumptionCreate, BudgetTaxResult,
    BudgetTaxCalculationResponse, BudgetTaxCashFlowResponse)
import app.crud as crud
from app.models.budget import TaxProfile as TaxProfileModel, TaxRate as TaxRateModel, TaxCalendarPeriod as CalendarModel, Budget as BudgetModel
from app.services.budgetTaxEngine import (
    BudgetTaxEngine,
    aggregate_tax_cash_flow,
    tax_cash_advance,
    tax_result_locations,
)

router=APIRouter()
def _role(user, write=False):
    role=getattr(getattr(user,'role',None),'role_name','') or ''
    access=getattr(getattr(user,'role',None),'access_type','') or ''
    role=(role+' '+access).strip().lower()
    allowed=('admin','financ','contab','account','gerent','manager')
    # A user without a role is never financial: reads must be denied too.
    if not role or not any(x in role for x in allowed):
        raise HTTPException(403,'Financial administration role required' if write else 'Financial role required')

@router.get('/profiles',response_model=List[TaxProfile])
def profiles(tax_year:Optional[int]=Query(None,ge=2000,le=2100),db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user);return crud.list_tax_profiles(db,tax_year)
def _active_profile_exists(db,tax_year,regime,id_company,exclude_id=None):
    """Only one active profile per company/year/regime; drafts and archived profiles are unrestricted."""
    q=db.query(TaxProfileModel).filter(TaxProfileModel.status=='active',TaxProfileModel.tax_year==tax_year,TaxProfileModel.regime==regime)
    q=q.filter(TaxProfileModel.id_company.is_(None) if id_company is None else TaxProfileModel.id_company==id_company)
    if exclude_id is not None:q=q.filter(TaxProfileModel.id_tax_profile!=exclude_id)
    return db.query(q.exists()).scalar()
@router.post('/profiles',response_model=TaxProfile,status_code=201)
def create_profile(payload:TaxProfileCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True)
    if payload.status=='active' and _active_profile_exists(db,payload.tax_year,payload.regime,payload.id_company):
        raise HTTPException(400,'Active tax profile already exists')
    try:
        return crud.create_tax_profile(db,payload)
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Tax profile conflicts with an existing profile')
@router.put('/profiles/{id_tax_profile}',response_model=TaxProfile)
def update_profile(id_tax_profile:int,payload:TaxProfileCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True)
    if payload.status=='active' and _active_profile_exists(db,payload.tax_year,payload.regime,payload.id_company,exclude_id=id_tax_profile):
        raise HTTPException(400,'Active tax profile already exists')
    try:
        obj=crud.update_tax_profile(db,id_tax_profile,payload)
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Tax profile conflicts with an existing profile')
    if not obj:raise HTTPException(404,f'TaxProfile {id_tax_profile} not found')
    return obj

@router.get('/rates',response_model=List[TaxRate])
def rates(tax_year:Optional[int]=Query(None,ge=2000,le=2100),tax_type:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user);return crud.list_tax_rates(db,tax_year,tax_type)
@router.post('/rates',response_model=TaxRate,status_code=201)
def create_rate(payload:TaxRateCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True);return crud.create_tax_rate(db,payload)
@router.put('/rates/{id_tax_rate}',response_model=TaxRate)
def update_rate(id_tax_rate:int,payload:TaxRateCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True);obj=crud.update_tax_rate(db,id_tax_rate,payload)
    if not obj:raise HTTPException(404,f'TaxRate {id_tax_rate} not found')
    return obj

@router.get('/calendar',response_model=List[TaxCalendar])
def calendar(tax_year:Optional[int]=Query(None,ge=2000,le=2100),regime:Optional[str]=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user);return crud.list_tax_calendar(db,tax_year,regime)
def _calendar_overlap_exists(db,payload,exclude_id=None):
    """Active periods of the same tax/year may not overlap. A shared (NULL regime) calendar
    conflicts with every regime, and a regime-specific one conflicts with the shared calendar."""
    if not payload.is_active:return False
    q=db.query(CalendarModel).filter(CalendarModel.tax_year==payload.tax_year,CalendarModel.tax_type==payload.tax_type,CalendarModel.is_active==True,CalendarModel.period_start<=payload.period_end,CalendarModel.period_end>=payload.period_start)
    if payload.regime is not None:q=q.filter(or_(CalendarModel.regime==payload.regime,CalendarModel.regime.is_(None)))
    if exclude_id is not None:q=q.filter(CalendarModel.id_tax_calendar_period!=exclude_id)
    return db.query(q.exists()).scalar()
@router.post('/calendar',response_model=TaxCalendar,status_code=201)
def create_calendar(payload:TaxCalendarCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True)
    if _calendar_overlap_exists(db,payload):raise HTTPException(400,'Calendar periods may not overlap')
    return crud.create_tax_calendar(db,payload)
@router.put('/calendar/{id_tax_calendar_period}',response_model=TaxCalendar)
def update_calendar(id_tax_calendar_period:int,payload:TaxCalendarCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True)
    if _calendar_overlap_exists(db,payload,exclude_id=id_tax_calendar_period):raise HTTPException(400,'Calendar periods may not overlap')
    obj=crud.update_tax_calendar(db,id_tax_calendar_period,payload)
    if not obj:raise HTTPException(404,f'TaxCalendarPeriod {id_tax_calendar_period} not found')
    return obj

@router.delete('/calendar/{id_tax_calendar_period}')
def delete_calendar(id_tax_calendar_period:int,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    """Delete a calendar period with write RBAC and transaction safety.

    Calendar rows are catalog data without foreign-key dependants.  Calculated
    budget tax results are independent snapshots (their period dates and
    amounts are persisted, not the calendar-period id), so they remain intact
    when this catalog row is removed.  A later calculation uses the current
    calendar catalog and may therefore produce a different set of snapshots.
    """
    _role(current_user,True)
    try:
        obj=crud.delete_tax_calendar(db,id_tax_calendar_period)
        if not obj:
            raise HTTPException(404,f'TaxCalendarPeriod {id_tax_calendar_period} not found')
        return {
            'message':'Tax calendar period deleted successfully',
            'deleted_id':id_tax_calendar_period,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Error deleting tax calendar period: {exc}',
        )

def _budget(db,id_budget):
    obj=db.query(BudgetModel).filter(BudgetModel.id_budget==id_budget).first()
    if not obj:raise HTTPException(404,f'Budget {id_budget} not found')
    return obj


def _check_profile_year(profile, budget):
    """A tax profile applies only to the fiscal year of the budget it is linked to."""
    if int(profile.tax_year) != int(budget.budget_year):
        raise HTTPException(400,f'Tax profile {profile.id_tax_profile} belongs to {profile.tax_year}; budget {budget.id_budget} is {budget.budget_year}')


def _simple_period_warning(rows):
    count = sum(1 for row in rows if row.tax_type == 'simple')
    return (f'SIMPLE requires six calculated bimonthly results; found {count}'
            if count and count != 6 else None)


def _result_payload(row, budget_year=None):
    """Serialize a tax snapshot with both P&L and cash coordinates.

    Do not rely on SQLAlchemy's internal ``__dict__`` here: the two P&L
    coordinates are intentionally snapshot metadata (stored in
    ``calculation_trace``), not physical columns, and must be explicit in the
    contract consumed by the frontend.
    """
    locations = tax_result_locations(row, budget_year)
    return {
        'id_budget_tax_result': row.id_budget_tax_result,
        'id_budget': row.id_budget,
        'id_budget_tax_assumption': row.id_budget_tax_assumption,
        'tax_type': row.tax_type,
        'period_start': row.period_start,
        'period_end': row.period_end,
        'taxable_base': row.taxable_base,
        'tax_rate': row.tax_rate,
        'tax_caused': row.tax_caused,
        'advance_amount': row.advance_amount,
        'withholding_amount': row.withholding_amount,
        'balance_payable': row.balance_payable,
        'declaration_date': row.declaration_date,
        'payment_date': locations['payment_date'],
        'payment_year': locations['payment_year'],
        'pnl_month': locations['pnl_month'],
        'pnl_year': locations['pnl_year'],
        'calculation_trace': row.calculation_trace or {},
        'warnings': row.warnings or [],
        'calculated_at': row.calculated_at,
    }
@router.get('/budgets/{id_budget}/assumptions',response_model=Optional[BudgetTaxAssumption])
def get_assumption(id_budget:int,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user);_budget(db,id_budget);return crud.get_budget_tax_assumption(db,id_budget)
@router.put('/budgets/{id_budget}/assumptions',response_model=BudgetTaxAssumption)
def put_assumption(id_budget:int,payload:BudgetTaxAssumptionCreate,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user,True);budget=_budget(db,id_budget)
    profile=crud.get_tax_profile(db,payload.id_tax_profile)
    if not profile:raise HTTPException(400,'Tax profile not found')
    _check_profile_year(profile,budget)
    return crud.upsert_budget_tax_assumption(db,id_budget,payload)
@router.post('/budgets/{id_budget}/calculate', response_model=BudgetTaxCalculationResponse)
def calculate(id_budget:int,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    # Calculating replaces the persisted snapshots, so it is a write operation.
    _role(current_user,True);budget=_budget(db,id_budget);a=crud.get_budget_tax_assumption(db,id_budget)
    if not a:raise HTTPException(400,'Tax assumptions are required')
    p=crud.get_tax_profile(db,a.id_tax_profile)
    if not p:raise HTTPException(400,'Tax profile not found')
    _check_profile_year(p,budget)
    result=BudgetTaxEngine(db).calculate(id_budget,a,p)
    return {'id_budget':id_budget,'regime':p.regime,'assumption':a,
             'warnings':result['warnings'],'totals':result['totals'],
             'results':[_result_payload(row, _budget(db, id_budget).budget_year)
                        for row in crud.list_budget_tax_results(db,id_budget)]}
@router.get('/budgets/{id_budget}/summary')
def summary(id_budget:int,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user);_budget(db,id_budget);rows=crud.list_budget_tax_results(db,id_budget)
    warnings = [] if rows else [
        f'Tax calculation has not been executed for budget {id_budget}'
    ]
    simple_warning = _simple_period_warning(rows)
    if simple_warning:
        warnings.append(simple_warning)
    by_type = {}
    for row in rows:
        item = by_type.setdefault(row.tax_type, {
            'tax_type': row.tax_type, 'taxable_base': Decimal('0'),
            'tax_caused': Decimal('0'), 'advance_amount': Decimal('0'),
            'withholding_amount': Decimal('0'), 'balance_payable': Decimal('0'),
        })
        for field in ('taxable_base', 'tax_caused', 'advance_amount',
                      'withholding_amount', 'balance_payable'):
            item[field] += getattr(row, field) or Decimal('0')
    total_advance = sum((r.advance_amount for r in rows), Decimal('0'))
    total_withholding = sum((r.withholding_amount for r in rows), Decimal('0'))
    total_payable = sum((r.balance_payable for r in rows), Decimal('0'))
    total_net_outflow = sum(
        (tax_cash_advance(r) + (r.balance_payable or Decimal('0'))
         for r in rows),
        Decimal('0'),
    )
    budget_year = _budget(db, id_budget).budget_year
    return {'id_budget':id_budget,
            'calculation_executed':bool(rows),
            'total_caused':sum((r.tax_caused for r in rows),Decimal('0')),
            'total_advance':total_advance,
            'total_withholding':total_withholding,
            'total_payable':total_payable,
             'total_net_outflow':total_net_outflow,
            'by_type':list(by_type.values()),
            'warnings':warnings,
             'results':[_result_payload(row, budget_year) for row in rows]}
REGIME_TAX_TYPES = ('income_ordinary', 'simple')


def _regime_summary(result):
    """Indicators of the regime-dependent tax only; ICA and credits are equal in both regimes."""
    rows = [row for row in result['results'] if row['tax_type'] in REGIME_TAX_TYPES]
    total = lambda values: sum(values, Decimal('0'))
    taxable = total(row['taxable_base'] for row in rows)
    caused = total(row['tax_caused'] for row in rows)
    advances = total(tax_cash_advance(row) for row in rows)
    payable = total(row['balance_payable'] for row in rows)
    return {
        'taxable_base': taxable,
        'tax_caused': caused,
        'advances': advances,
        'withholdings': total(row['withholding_amount'] for row in rows),
        'payable_balance': payable,
        'annual_total': advances + payable,
        'effective_rate': (caused / taxable).quantize(Decimal('0.000001')) if taxable > 0 else None,
    }


@router.get('/budgets/{id_budget}/comparison')
def comparison(id_budget:int,regime_a:str='ordinary',regime_b:str='simple',db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    """Read-only projection of both regimes. It never replaces persisted snapshots."""
    _role(current_user);budget=_budget(db,id_budget)
    if {regime_a,regime_b}!={'ordinary','simple'}:
        raise HTTPException(400,'regime_a and regime_b must be ordinary and simple, in any order')
    assumption=crud.get_budget_tax_assumption(db,id_budget)
    profiles=crud.list_tax_profiles(db,budget.budget_year)
    warnings=[]
    summaries={}
    for regime in (regime_a,regime_b):
        profile=next((p for p in profiles if p.regime==regime and p.status in ('active','draft')),None)
        if profile is None:
            warnings.append(f'Missing tax profile for {regime} ({budget.budget_year})')
            summaries[regime]=None
        elif assumption is None:
            warnings.append('Tax assumptions are required')
            summaries[regime]=None
        else:
            result=BudgetTaxEngine(db).calculate(id_budget,assumption,profile,persist=False)
            warnings.extend(result['warnings'])
            summaries[regime]=_regime_summary(result)
    ordinary,simple=summaries['ordinary'],summaries['simple']
    difference=None
    if ordinary and simple:
        difference={key:(simple[key]-ordinary[key] if simple[key] is not None and ordinary[key] is not None else None)
                    for key in ordinary}
    return {
        'id_budget':id_budget,
        'warnings':sorted(set(warnings)),
        'ordinary':ordinary,
        'simple':simple,
        'difference':difference,
        'difference_basis':'simple - ordinary',
    }
@router.get('/budgets/{id_budget}/cash-flow', response_model=BudgetTaxCashFlowResponse)
def cash_flow(id_budget:int,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    _role(current_user)
    _budget(db,id_budget)
    rows = crud.list_budget_tax_results(db,id_budget)
    aggregated = aggregate_tax_cash_flow(rows)
    warnings = list(aggregated['warnings'])
    if not rows:
        warnings.insert(0, f'Tax calculation has not been executed for budget {id_budget}')
    simple_warning = _simple_period_warning(rows)
    if simple_warning:
        warnings.append(simple_warning)
    return {
        'id_budget': id_budget,
        'calculation_executed': bool(rows),
        'monthly': aggregated['monthly'],
        'totals': aggregated['totals'],
        'warnings': sorted(set(warnings)),
    }
