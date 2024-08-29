# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.customer import Customer as CustomerModel
from app.schemas.customer import CustomerCreate, Customer as CustomerSchema


def create_customer(db: Session, customer: CustomerCreate) -> CustomerSchema:
    db_customer = CustomerModel(**customer.model_dump())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    return db_customer

def get_customer_by_id(db: Session, id_customer: int) -> CustomerSchema:    
    result = db.query(CustomerModel).filter(CustomerModel.id_customer == id_customer).first()
    return result

def get_customers(db: Session, skip: int = 0, limit: int = 10) -> list[CustomerSchema]:
    return db.query(CustomerModel).offset(skip).limit(limit).all()

def update_customer(db: Session, id_customer: int, customer: CustomerCreate) -> CustomerSchema:
    db_customer = db.query(CustomerModel).filter(CustomerModel.id_customer == id_customer).first()
    if db_customer:
        for key, value in customer.model_dump().items():
            setattr(db_customer, key, value)
        db.commit()
        db.refresh(db_customer)
    return db_customer

def delete_customer(db: Session, id_customer: int):
    db_customer = db.query(CustomerModel).filter(CustomerModel.id_customer == id_customer).first()
    if db_customer:
        db.delete(db_customer)
        db.commit()
        return True
    return False