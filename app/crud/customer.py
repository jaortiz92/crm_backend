# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.customer import Customer as CustomerModel
from app.schemas.customer import CustomerCreate, Customer as CustomerSchema
from app.crud.utils import Constants
from app.crud.utils import statusRequest
import app.crud as crud


def get_customer_by_id(db: Session, id_customer: int) -> CustomerSchema:
    result = db.query(CustomerModel).filter(
        CustomerModel.id_customer == id_customer).first()
    return result


def get_customer_by_document(db: Session, document: int) -> CustomerSchema:
    result = db.query(CustomerModel).filter(
        CustomerModel.id_customer == document).first()
    return result


def create_customer(db: Session, customer: CustomerCreate) -> CustomerSchema:
    status = statusRequest()
    db_customer = CustomerModel(**customer.model_dump())
    if get_customer_by_id(db, db_customer.document):
        status['value_already_registered'] = True
        return status
    else:
        db.add(db_customer)
        db.commit()
        db.refresh(db_customer)
        return db_customer


def get_customers(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[CustomerSchema]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(CustomerModel).order_by(
            CustomerModel.company_name.asc()
        ).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        result = db.query(CustomerModel).filter(
            CustomerModel.id_seller == id_user
        ).order_by(
            CustomerModel.company_name.asc()
        ).offset(skip).limit(limit).all()
    return result


def update_customer(db: Session, id_customer: int, customer: CustomerCreate) -> CustomerSchema:
    db_customer = db.query(CustomerModel).filter(
        CustomerModel.id_customer == id_customer).first()
    if db_customer:
        for key, value in customer.model_dump().items():
            setattr(db_customer, key, value)
        db.commit()
        db.refresh(db_customer)
    return db_customer


def delete_customer(db: Session, id_customer: int):
    db_customer = db.query(CustomerModel).filter(
        CustomerModel.id_customer == id_customer).first()
    if db_customer:
        db.delete(db_customer)
        db.commit()
        return True
    return False
