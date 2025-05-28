# Python
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
import io
import pandas as pd
from pandas.core.frame import DataFrame


# App
from app.models.customer import Customer as CustomerModel
from app.models.brand import Brand as BrandModel
from app.models.customerBrand import CustomerBrand as CustomerBrandModel
from app.models.city import City as CityModel
from app.models.user import User as UserModel
from app.models.storeType import StoreType as StoreTypeModel
from app.schemas.customer import CustomerCreate, Customer as CustomerSchema
from app.crud.utils import Constants
from app.crud.utils import statusRequest, convert_numpy_types
from app.utils.templates import CustomersTemplate


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


async def create_or_update_customers(db: Session, file: UploadFile, create: bool) -> list[CustomerSchema]:
    stream = io.BytesIO()
    content = await file.read()
    stream.write(content)

    # Read Excel file from the BytesIO stream
    try:
        df: DataFrame = CustomersTemplate(
            content
        ).customers
    except Exception as e:
        print(e)
        return False

    customers_to_update = []
    customers_to_create = []

    for index, row in df.iterrows():
        try:
            # Validar llaves foráneas
            flag = []
            if not pd.isna(row["id_city"]):
                city = db.query(CityModel).filter_by(
                    city_name=row["id_city"]
                ).first()
                if city:
                    df.loc[index, "id_city"] = city.id_city
                else:
                    flag.append("City")

            if not pd.isna(row["id_seller"]):
                seller = db.query(UserModel).filter_by(
                    username=row["id_seller"]
                ).first()
                if seller:
                    df.loc[index, "id_seller"] = seller.id_user
                else:
                    flag.append("Seller")

            if not pd.isna(row["id_store_type"]):
                store_type = db.query(StoreTypeModel).filter_by(
                    store_type=row["id_store_type"]
                ).first()
                if store_type:
                    df.loc[index, "id_store_type"] = store_type.id_store_type
                else:
                    flag.append("Store_type")

            if len(flag) > 0:
                raise ValueError(f"Error en llaves foráneas {flag} en {row}")

            # Validate if Document exist
            existing_customer = db.query(CustomerModel).filter_by(
                document=row["document"]).first()

            if existing_customer and create:
                raise ValueError(
                    f"Cliente con documento {row['document']} ya existe"
                )
            elif existing_customer:
                customer_data = {
                    k: convert_numpy_types(v)
                    for k, v in df.loc[index, :].items() if not pd.isna(v)
                }
                for key, value in customer_data.items():
                    setattr(existing_customer, key, value)
                customers_to_update.append(existing_customer)
            else:
                customer_data = {
                    k: convert_numpy_types(v)
                    for k, v in df.loc[index, :].items() if not pd.isna(v)
                }
                customers_to_create.append(customer_data)

        except Exception as e:
            return {"error": str(e)}

    if create:
        db.bulk_insert_mappings(CustomerModel, customers_to_create)
    else:
        for customer in customers_to_update:
            db.merge(customer)
    db.commit()
    return True


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
