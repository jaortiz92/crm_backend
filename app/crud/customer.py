# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.customer import Customer as CustomerModel
from app.models.brand import Brand as BrandModel
from app.models.customerBrand import CustomerBrand as CustomerBrandModel
from app.schemas.customer import CustomerCreate, Customer as CustomerSchema
from app.crud.utils import Constants
from app.crud.utils import statusRequest


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

    brand_ids = customer.brand_ids
    db_customer = CustomerModel(**customer.model_dump(exclude={"brand_ids"}))
    if get_customer_by_id(db, db_customer.document):
        status['value_already_registered'] = True
        return status
    else:
        for brand_id in brand_ids:
            db_brand = db.query(BrandModel).filter(
                BrandModel.id_brand == brand_id).first()
            if db_brand:
                db_customer.brands.append(db_brand)
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


def get_id_customers_by_seller(db: Session, id_seller: int) -> list[int]:
    customers = db.query(CustomerModel.id_customer).filter(
        CustomerModel.id_seller == id_seller
    ).all()
    return [customer[0] for customer in customers]


def update_customer(db: Session, id_customer: int, customer: CustomerCreate) -> CustomerSchema:
    db_customer = db.query(CustomerModel).filter(
        CustomerModel.id_customer == id_customer).first()
    if db_customer:
        for key, value in customer.model_dump().items():
            setattr(db_customer, key, value)

        current_brands = (
            db.query(CustomerBrandModel.id_brand)
            .filter(CustomerBrandModel.id_customer == id_customer)
            .all()
        )

        current_brands = {
            current_brand.id_brand for current_brand in current_brands
        }

        new_brand_ids = set(customer.brand_ids)
        brands_to_add = new_brand_ids - current_brands
        brands_to_remove = current_brands - new_brand_ids

        if brands_to_remove:
            db.query(CustomerBrandModel).filter(
                CustomerBrandModel.id_customer == id_customer,
                CustomerBrandModel.id_brand.in_(brands_to_remove)
            ).delete(synchronize_session=False)

        for id_brand in brands_to_add:
            db_brand = db.query(BrandModel).filter(
                BrandModel.id_brand == id_brand).first()
            if db_brand:
                current_brand = CustomerBrandModel(
                    id_customer=id_customer,
                    id_brand=id_brand
                )
                db.add(current_brand)

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
