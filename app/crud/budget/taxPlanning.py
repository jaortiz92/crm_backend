from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.budget import TaxProfile, TaxRate, TaxCalendarPeriod, BudgetTaxAssumption, BudgetTaxResult

def list_tax_profiles(db: Session, tax_year: Optional[int] = None):
    q = db.query(TaxProfile)
    if tax_year is not None: q = q.filter(TaxProfile.tax_year == tax_year)
    return q.order_by(TaxProfile.tax_year, TaxProfile.id_tax_profile).all()
def get_tax_profile(db: Session, id_tax_profile: int): return db.query(TaxProfile).filter(TaxProfile.id_tax_profile == id_tax_profile).first()
def create_tax_profile(db: Session, payload):
    obj = TaxProfile(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return obj
def update_tax_profile(db: Session, id_tax_profile: int, payload):
    obj = get_tax_profile(db, id_tax_profile)
    if not obj: return None
    for k,v in payload.model_dump().items(): setattr(obj,k,v)
    db.commit(); db.refresh(obj); return obj

def list_tax_rates(db: Session, tax_year: Optional[int] = None, tax_type: Optional[str] = None):
    q = db.query(TaxRate)
    if tax_year is not None: q=q.filter(TaxRate.tax_year == tax_year)
    if tax_type is not None: q=q.filter(TaxRate.tax_type == tax_type)
    return q.order_by(TaxRate.tax_year, TaxRate.tax_type, TaxRate.income_min).all()
def get_tax_rate(db: Session, id_tax_rate: int): return db.query(TaxRate).filter(TaxRate.id_tax_rate == id_tax_rate).first()
def create_tax_rate(db: Session, payload):
    obj=TaxRate(**payload.model_dump()); db.add(obj); db.commit(); db.refresh(obj); return obj
def update_tax_rate(db: Session, id_tax_rate: int, payload):
    obj=get_tax_rate(db,id_tax_rate)
    if not obj:return None
    for k,v in payload.model_dump().items():setattr(obj,k,v)
    db.commit();db.refresh(obj);return obj

def list_tax_calendar(db: Session, tax_year: Optional[int] = None, regime: Optional[str] = None):
    q=db.query(TaxCalendarPeriod)
    if tax_year is not None:q=q.filter(TaxCalendarPeriod.tax_year==tax_year)
    # A NULL regime is a shared calendar according to the catalog contract;
    # it must remain visible when calculating either ordinary or SIMPLE.
    if regime is not None:
        q = q.filter(or_(TaxCalendarPeriod.regime == regime,
                         TaxCalendarPeriod.regime.is_(None)))
    return q.order_by(TaxCalendarPeriod.tax_year,TaxCalendarPeriod.sequence).all()
def get_tax_calendar(db: Session, id_period: int):return db.query(TaxCalendarPeriod).filter(TaxCalendarPeriod.id_tax_calendar_period==id_period).first()
def create_tax_calendar(db: Session,payload):
    obj=TaxCalendarPeriod(**payload.model_dump());db.add(obj);db.commit();db.refresh(obj);return obj
def update_tax_calendar(db: Session,id_period:int,payload):
    obj=get_tax_calendar(db,id_period)
    if not obj:return None
    for k,v in payload.model_dump().items():setattr(obj,k,v)
    db.commit();db.refresh(obj);return obj

def delete_tax_calendar(db: Session, id_period: int):
    """Delete a tax calendar period and return the deleted row.

    Calendar periods have no foreign-key dependants.  ``BudgetTaxResult``
    stores the dates and amounts used for a calculation as a snapshot and
    does not reference this catalog row, so deleting a period must not delete
    or rewrite already calculated results.  If the commit fails, restore the
    transaction before propagating the error so callers cannot observe a
    partial delete.
    """
    try:
        obj = get_tax_calendar(db, id_period)
        if not obj:
            return None
        db.delete(obj)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return obj

def get_budget_tax_assumption(db: Session,id_budget:int):return db.query(BudgetTaxAssumption).filter(BudgetTaxAssumption.id_budget==id_budget).first()
def upsert_budget_tax_assumption(db: Session,id_budget:int,payload):
    obj=get_budget_tax_assumption(db,id_budget)
    values=payload.model_dump()
    if obj:
        for k,v in values.items():setattr(obj,k,v)
    else:
        obj=BudgetTaxAssumption(id_budget=id_budget,**values);db.add(obj)
    db.commit();db.refresh(obj);return obj
def clear_budget_tax_results(db: Session,id_budget:int):
    db.query(BudgetTaxResult).filter(BudgetTaxResult.id_budget==id_budget).delete(synchronize_session=False)
def add_budget_tax_result(db: Session,**values):
    obj=BudgetTaxResult(**values);db.add(obj);return obj
def list_budget_tax_results(db: Session,id_budget:int):return db.query(BudgetTaxResult).filter(BudgetTaxResult.id_budget==id_budget).order_by(BudgetTaxResult.payment_date,BudgetTaxResult.tax_type).all()
