# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

# App
from app.models.order import Order as OrderModel
from app.schemas.order import OrderCreate, Order as OrderSchema
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.models.customer import Customer
from app.models.user import User
from app.models.paymentMethod import PaymentMethod
import app.crud as crud
from app.crud.utils import statusRequest
from app.crud.utils import Constants


def validate_foreign_keys(db: Session, order: OrderSchema) -> list:  # | None:
    foreign_keys: list[list] = [
        [crud.get_customer_trip_by_id, order.id_customer_trip, "Custormer Trip"],
        [crud.get_user_by_id, order.id_seller, "User"],
        # [crud.get_payment_method_by_id, order.id_payment_method, "Payment method"],
    ]
    for foreign_key in foreign_keys:
        if not foreign_key[0](db, foreign_key[1]):
            return [foreign_key[2], foreign_key[1]]
    return Constants.STATUS_OK


def get_order_by_id(db: Session, id_order: int) -> OrderSchema:
    return db.query(OrderModel).filter(OrderModel.id_order == id_order).first()


def get_order_by_id_with_details(db: Session, id_order: int) -> OrderModel:
    return db.query(OrderModel).options(
        joinedload(OrderModel.order_details)
    ).filter(
        OrderModel.id_order == id_order
    ).first()


def get_orders(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[OrderSchema]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(OrderModel).order_by(
            OrderModel.id_order.desc()
        ).offset(skip).limit(limit).all()

    elif auth == Constants.FILTER:
        result = db.query(OrderModel).filter(
            OrderModel.id_seller == id_user
        ).order_by(
            OrderModel.id_order.desc()
        ).offset(skip).limit(limit).all()
    return result


def get_orders_by_id_customer(db: Session, id_customer) -> list[OrderSchema]:
    return db.query(OrderModel).join(CustomerTripModel).filter(
        CustomerTripModel.id_customer == id_customer
    ).all()


def get_orders_by_id_customer_trip(db: Session, id_customer_trip) -> list[OrderSchema]:
    return db.query(OrderModel).join(CustomerTripModel).filter(
        CustomerTripModel.id_customer_trip == id_customer_trip
    ).all()


def create_order(db: Session, order: OrderCreate) -> OrderSchema:  # | list:
    status = statusRequest()
    db_order = get_order_by_id(db, order.id_order)
    if db_order:
        status['user_already_registered'] = True
        return status
    validation: list = validate_foreign_keys(db, order)
    if validation != Constants.STATUS_OK:
        return validation
    else:
        db_order = OrderModel(**order.model_dump())
        db.add(db_order)
        db.commit()
        db.refresh(db_order)
        return db_order


# | list:
def update_order(db: Session, id_order: int, order: OrderCreate) -> OrderSchema:
    db_order = db.query(OrderModel).filter(
        OrderModel.id_order == id_order).first()
    if db_order:
        validation: list = validate_foreign_keys(db, order)
        if validation != Constants.STATUS_OK:
            return validation
        else:
            for key, value in order.model_dump().items():
                setattr(db_order, key, value)
            db.commit()
            db.refresh(db_order)
    return db_order


def delete_order(db: Session, id_order: int) -> bool:
    db_order = db.query(OrderModel).filter(
        OrderModel.id_order == id_order).first()
    if db_order:
        db.delete(db_order)
        db.commit()
        return True
    return False
