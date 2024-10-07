# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.orderDetail import OrderDetail as OrderDetailModel
from app.schemas.orderDetail import OrderDetailCreate, OrderDetail as OrderDetailSchema


def create_order_detail(db: Session, order_detail: OrderDetailCreate) -> OrderDetailSchema:
    db_order_detail = OrderDetailModel(**order_detail.model_dump())
    db.add(db_order_detail)
    db.commit()
    db.refresh(db_order_detail)
    return db_order_detail


def get_order_detail_by_id(db: Session, id_order_detail: int) -> OrderDetailSchema:
    result = db.query(OrderDetailModel).filter(
        OrderDetailModel.id_order_detail == id_order_detail).first()
    return result


def get_order_details(db: Session, skip: int = 0, limit: int = 10) -> list[OrderDetailSchema]:
    return db.query(OrderDetailModel).offset(skip).limit(limit).all()


def update_order_detail(db: Session, id_order_detail: int, order_detail: OrderDetailCreate) -> OrderDetailSchema:
    db_order_detail = db.query(OrderDetailModel).filter(
        OrderDetailModel.id_order_detail == id_order_detail).first()
    if db_order_detail:
        for key, value in order_detail.model_dump().items():
            setattr(db_order_detail, key, value)
        db.commit()
        db.refresh(db_order_detail)
    return db_order_detail


def delete_order_detail(db: Session, id_order_detail: int):
    db_order_detail = db.query(OrderDetailModel).filter(
        OrderDetailModel.id_order_detail == id_order_detail).first()
    if db_order_detail:
        db.delete(db_order_detail)
        db.commit()
        return True
    return False
