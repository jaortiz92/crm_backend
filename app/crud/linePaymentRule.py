from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.linePaymentRule import LinePaymentRule as LinePaymentRuleModel
from app.schemas.linePaymentRule import LinePaymentRuleCreate


def create_line_payment_rule(
    db: Session, line_payment_rule: LinePaymentRuleCreate
) -> LinePaymentRuleModel:
    db_rule = LinePaymentRuleModel(**line_payment_rule.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


def get_line_payment_rules_by_line(
    db: Session, id_line: int
) -> List[LinePaymentRuleModel]:
    return db.query(LinePaymentRuleModel).filter(
        LinePaymentRuleModel.id_line == id_line
    ).all()


def create_line_payment_rules_bulk(
    db: Session, rules: List[LinePaymentRuleCreate]
) -> List[LinePaymentRuleModel]:
    db_rules = [LinePaymentRuleModel(**r.model_dump()) for r in rules]
    db.bulk_save_objects(db_rules)
    db.commit()
    return db_rules


def get_line_payment_rule_by_id(
    db: Session, id_line_payment_rule: int
) -> Optional[LinePaymentRuleModel]:
    return db.query(LinePaymentRuleModel).filter(
        LinePaymentRuleModel.id_line_payment_rule == id_line_payment_rule
    ).first()


def update_line_payment_rule(
    db: Session, id_line_payment_rule: int, rule: LinePaymentRuleCreate
) -> Optional[LinePaymentRuleModel]:
    db_rule = db.query(LinePaymentRuleModel).filter(
        LinePaymentRuleModel.id_line_payment_rule == id_line_payment_rule
    ).first()
    if db_rule:
        for key, value in rule.model_dump().items():
            setattr(db_rule, key, value)
        db.commit()
        db.refresh(db_rule)
    return db_rule


def delete_line_payment_rule(db: Session, id_line_payment_rule: int) -> bool:
    db_rule = db.query(LinePaymentRuleModel).filter(
        LinePaymentRuleModel.id_line_payment_rule == id_line_payment_rule
    ).first()
    if db_rule:
        db.delete(db_rule)
        db.commit()
        return True
    return False
