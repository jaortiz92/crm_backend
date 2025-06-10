# Python
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
import io
import pandas as pd
from pandas.core.frame import DataFrame

# App
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.schemas.customerTrip import CustomerTripCreate, CustomerTrip as CustomerTripSchema
import app.crud as crud
from app.crud.utils import Constants
from app.utils.templates import CustomerTripsTemplate
from app.models.user import User as UserModel
from app.models.collection import Collection as CollectionModel
from app.models.customer import Customer as CustomerModel
from app.crud.utils import statusRequest, convert_numpy_types


def get_customer_trip_by_id(db: Session, id_customer_trip: int) -> CustomerTripModel:
    return db.query(CustomerTripModel).filter(CustomerTripModel.id_customer_trip == id_customer_trip).first()


def get_customer_trips(db: Session, id_user: int, access_type: str, skip: int = 0, limit: int = 10) -> list[CustomerTripModel]:
    auth = Constants.get_auth_to_customers(access_type)
    result = []
    if auth == Constants.ALL:
        result = db.query(CustomerTripModel).order_by(
            CustomerTripModel.id_customer_trip.desc()).offset(skip).limit(limit).all()
    elif auth == Constants.FILTER:
        result = db.query(CustomerTripModel).filter(
            CustomerTripModel.id_seller == id_user).order_by(
            CustomerTripModel.id_customer_trip.desc()).offset(skip).limit(limit).all()
    return result


def get_customer_trips_by_id_customer(db: Session, id_customer) -> list[CustomerTripModel]:
    return db.query(CustomerTripModel).filter(CustomerTripModel.id_customer == id_customer).order_by(
        CustomerTripModel.id_customer_trip.desc()
    ).all()


def create_customer_trip(db: Session, customer_trip: CustomerTripCreate) -> CustomerTripModel:
    db_customer_trip = CustomerTripModel(**customer_trip.model_dump())
    db.add(db_customer_trip)
    db.commit()
    db.refresh(db_customer_trip)
    return db_customer_trip


def update_customer_trip(db: Session, id_customer_trip: int, customer_trip: CustomerTripCreate) -> CustomerTripModel:
    db_customer_trip = db.query(CustomerTripModel).filter(
        CustomerTripModel.id_customer_trip == id_customer_trip).first()

    if db_customer_trip:
        for key, value in customer_trip.model_dump().items():
            setattr(db_customer_trip, key, value)
        db.commit()
        db.refresh(db_customer_trip)
    return db_customer_trip


async def create_or_update_customer_trips(db: Session, file: UploadFile, create: bool) -> list[CustomerTripSchema]:
    stream = io.BytesIO()
    content = await file.read()
    stream.write(content)

    # Read Excel file from the BytesIO stream
    try:
        df: DataFrame = CustomerTripsTemplate(
            content, create
        ).customers
    except Exception as e:
        print(e)
        return False

    customer_trips_to_update = []
    customer_trips_to_create = []

    for index, row in df.iterrows():
        try:
            # Validar llaves foráneas
            flag = []

            if not pd.isna(row["id_seller"]):
                seller = db.query(UserModel).filter_by(
                    username=row["id_seller"]
                ).first()
                if seller:
                    df.loc[index, "id_seller"] = str(seller.id_user)
                else:
                    flag.append("Seller")

            if not pd.isna(row["id_collection"]):
                collection = db.query(CollectionModel).filter_by(
                    short_collection_name=row["id_collection"]
                ).first()
                if collection:
                    df.loc[index, "id_collection"] = str(
                        collection.id_collection)
                else:
                    flag.append("Collection")

            if not pd.isna(row["id_customer"]):
                customer = db.query(CustomerModel).filter_by(
                    document=row["id_customer"]
                ).first()
                if customer:
                    df.loc[index, "id_customer"] = str(
                        customer.id_customer)
                else:
                    flag.append("Customer")

            if len(flag) > 0:
                raise ValueError(
                    f"Error en llaves foráneas {flag} en {row['id_customer']}")

            # Validate if Document exist
            existing_customer_trip = db.query(CustomerTripModel).filter_by(
                id_customer_trip=row["id_customer_trip"]).first()

            if not existing_customer_trip and not create:
                raise ValueError(
                    f"Viaje del cliente {row['id_customer_trip']} no existe"
                )
            elif existing_customer_trip:
                customer_trip_data = {
                    k: convert_numpy_types(v)
                    for k, v in df.loc[index, :].items() if not pd.isna(v)
                }
                for key, value in customer_trip_data.items():
                    setattr(existing_customer_trip, key, value)
                customer_trips_to_update.append(existing_customer_trip)
            else:
                customer_trip_data = {
                    k: convert_numpy_types(v)
                    for k, v in df.loc[index, :].items() if not pd.isna(v)
                }
                customer_trips_to_create.append(customer_trip_data)

        except Exception as e:
            return {"error": str(e)}

    if create:
        db.bulk_insert_mappings(CustomerTripModel, customer_trips_to_create)
    else:
        for customer in customer_trips_to_update:
            db.merge(customer)
    db.commit()
    return True


def delete_customer_trip(db: Session, id_customer_trip: int) -> bool:

    db_customer_trip = db.query(CustomerTripModel).filter(
        CustomerTripModel.id_customer_trip == id_customer_trip).first()
    db_activities = crud.get_activities_by_id_customer_trip(
        db, id_customer_trip
    )
    for db_activity in db_activities:
        crud.delete_activity(db, db_activity.id_activity)
    if db_customer_trip:
        db.delete(db_customer_trip)
        db.commit()
        return True
    return False
