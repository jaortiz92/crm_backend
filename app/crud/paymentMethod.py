# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.paymentMethod import PaymentMethod as PaymentMethodModel
from app.schemas.paymentMethod import PaymentMethod as PaymentMethodSchema


def get_payment_method_by_id(db: Session, id_payment_method: int) -> PaymentMethodSchema:
    result = db.query(PaymentMethodModel).filter(
        PaymentMethodModel.id_payment_method == id_payment_method).first()
    return result


def get_payment_methods(db: Session, skip: int = 0, limit: int = 10) -> list[PaymentMethodSchema]:
    return db.query(PaymentMethodModel).offset(skip).limit(limit).all()


def get_payments_method_by_name(db: Session, payment_method_name: str) -> list[PaymentMethodSchema]:
    search_pattern = f"%{payment_method_name}%"
    return db.query(PaymentMethodModel).filter(
        PaymentMethodModel.payment_method_name.ilike(search_pattern)).all()
