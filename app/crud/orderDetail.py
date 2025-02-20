# Python
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
import io
import pandas as pd

# App
from app.models.orderDetail import OrderDetail as OrderDetailModel
from app.schemas.orderDetail import OrderDetailCreate, OrderDetail as OrderDetailSchema


def create_order_detail(db: Session, order_detail: OrderDetailCreate) -> OrderDetailSchema:
    db_order_detail = OrderDetailModel(**order_detail.model_dump())
    db.add(db_order_detail)
    db.commit()
    db.refresh(db_order_detail)
    return db_order_detail


async def create_order_details(db: Session, id_order: int, details: UploadFile) -> list[OrderDetailSchema]:
    stream = io.BytesIO()
    print(1)
    content = await details.read()
    stream.write(content)

    # Read Excel file from the BytesIO stream
    df = pd.read_excel(
        stream,
        sheet_name='PEDIDO',
        header=5
    )
    print(df)
    print(2)
    return 'ok'


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
