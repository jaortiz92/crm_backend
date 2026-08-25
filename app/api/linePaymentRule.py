from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.schemas import LinePaymentRule, LinePaymentRuleCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

line_payment_rule = APIRouter(
    prefix="/line-payment-rule",
    tags=["Line Payment Rules"],
)


@line_payment_rule.get("/{id_line_payment_rule}", response_model=LinePaymentRule)
def get_line_payment_rule_by_id(
    id_line_payment_rule: int, db: Session = Depends(get_db)
):
    db_rule = crud.get_line_payment_rule_by_id(db, id_line_payment_rule)
    if db_rule is None:
        Exceptions.register_not_found("LinePaymentRule", id_line_payment_rule)
    return db_rule


@line_payment_rule.get("/by-line/{id_line}", response_model=List[LinePaymentRule])
def get_line_payment_rules_by_line(
    id_line: int, db: Session = Depends(get_db)
):
    return crud.get_line_payment_rules_by_line(db, id_line)


@line_payment_rule.post("/", response_model=LinePaymentRule)
def create_line_payment_rule(
    rule: LinePaymentRuleCreate, db: Session = Depends(get_db)
):
    return crud.create_line_payment_rule(db, rule)


@line_payment_rule.put("/{id_line_payment_rule}", response_model=LinePaymentRule)
def update_line_payment_rule(
    id_line_payment_rule: int,
    rule: LinePaymentRuleCreate,
    db: Session = Depends(get_db),
):
    db_rule = crud.update_line_payment_rule(db, id_line_payment_rule, rule)
    if db_rule is None:
        Exceptions.register_not_found("LinePaymentRule", id_line_payment_rule)
    return db_rule


@line_payment_rule.delete("/{id_line_payment_rule}")
def delete_line_payment_rule(
    id_line_payment_rule: int, db: Session = Depends(get_db)
):
    success = crud.delete_line_payment_rule(db, id_line_payment_rule)
    if not success:
        Exceptions.register_not_found("LinePaymentRule", id_line_payment_rule)
    return {"message": "Line payment rule deleted successfully"}
