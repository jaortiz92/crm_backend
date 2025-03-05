# Python
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import io
from pandas.core.frame import DataFrame


# App
from app.models.orderDetail import OrderDetail as OrderDetailModel
from app.models.brand import Brand as BrandModel
from app.schemas.orderDetail import OrderDetailCreate, OrderDetail as OrderDetailSchema
from app.utils.process_details import ProcessDetailsOrders
from app.crud.utils import Constants


def create_order_detail(db: Session, order_detail: OrderDetailCreate) -> OrderDetailSchema:
    db_order_detail = OrderDetailModel(**order_detail.model_dump())
    db.add(db_order_detail)
    db.commit()
    db.refresh(db_order_detail)
    return db_order_detail


async def create_order_details(db: Session, id_order: int, type_format: str, details: UploadFile) -> list[OrderDetailSchema]:
    stream = io.BytesIO()
    content = await details.read()
    stream.write(content)

    # Read Excel file from the BytesIO stream
    try:
        df: DataFrame = ProcessDetailsOrders(
            stream, id_order, type_format
        ).final_details
    except Exception as e:
        print(e)
        return False

    # Delete last orders_detail
    delete_orders_detail_by_id_order(db, id_order)
    rows = df.to_dict(orient='records')
    db.bulk_insert_mappings(OrderDetailModel, rows)
    db.commit()
    return True


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


def delete_orders_detail_by_id_order(db: Session, id_order: int):
    db.query(
        OrderDetailModel
    ).filter(
        OrderDetailModel.id_order == id_order
    ).delete(
        synchronize_session=False
    )

    db.commit()


def get_order_detail_by_brand_and_id_order(db: Session, id_order: int):
    result = db.query(
        BrandModel.brand_name,
        OrderDetailModel.gender,
        func.sum(OrderDetailModel.quantity).label("quantity"),
        func.sum(OrderDetailModel.value_without_tax).label(
            "value_without_tax"),
        func.sum(OrderDetailModel.value_with_tax).label("value_with_tax")
    ).join(
        BrandModel, OrderDetailModel.id_brand == BrandModel.id_brand
    ).filter(
        OrderDetailModel.id_order == id_order
    ).group_by(
        BrandModel.brand_name, OrderDetailModel.gender
    ).order_by(
        BrandModel.brand_name.asc(),
        OrderDetailModel.gender.desc()
    ).all()

    return result


def get_order_detail_by_description_and_id_order(db: Session, id_order: int):
    result = db.query(
        OrderDetailModel.description,
        func.sum(OrderDetailModel.quantity).label("quantity"),
        func.sum(OrderDetailModel.value_without_tax).label(
            "value_without_tax"
        )
    ).filter(
        OrderDetailModel.id_order == id_order
    ).group_by(
        OrderDetailModel.description
    ).order_by(
        desc(func.sum(OrderDetailModel.quantity))
    ).all()
    return result


def get_order_detail_by_size_and_id_order(db: Session, id_order: int):
    result = db.query(
        OrderDetailModel.size,
        func.sum(OrderDetailModel.quantity).label("quantity"),
        func.sum(OrderDetailModel.value_without_tax).label(
            "value_without_tax"
        )
    ).filter(
        OrderDetailModel.id_order == id_order
    ).group_by(
        OrderDetailModel.size
    ).order_by(
        desc(func.sum(OrderDetailModel.quantity))
    ).all()
    return result
