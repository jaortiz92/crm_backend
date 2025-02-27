# Python
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import OrderDetail, OrderDetailCreate, OrderDetailFull, OrderDetailByBrand
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions
from app.utils.constants import Constants

order_detail = APIRouter(
    prefix="/order_detail",
    tags=["OrderDetail"],
)


@order_detail.get("/{id_order_detail}", response_model=OrderDetail)
def get_order_detail_by_id(id_order_detail: int, db: Session = Depends(get_db)):
    """
    Show an Order Detail

    This path operation shows an order detail in the app.

    Parameters:
    - Register path parameter
        - id_order_detail: int

    Returns a JSON with the order detail:
        - id_order integer
        - product string
        - color string
        - size string
        - id_brand integer
        - gender integer
        - unit_value float
        - quantity integer
        - value_without_tax float
        - discount float
        - value_with_tax float
        - id_order_detail
    """
    db_order_detail = crud.get_order_detail_by_id(db, id_order_detail)
    if db_order_detail is None:
        Exceptions.register_not_found("Order Detail", id_order_detail)
    return db_order_detail


@order_detail.get("/full/{id_order_detail}", response_model=OrderDetailFull)
def get_order_detail_by_id_full(id_order_detail: int, db: Session = Depends(get_db)):
    """
    Show an Order Detail Full

    This path operation shows an order detail full in the app.

    Parameters:
    - Register path parameter
        - id_order_detail: int

    Returns a JSON with the order detail full:
        - id_order integer
        - product string
        - color string
        - size string
        - id_brand integer
        - gender integer
        - unit_value float
        - quantity integer
        - value_without_tax float
        - discount float
        - value_with_tax float
        - id_order_detail
        - order: OrderBase
        - brand: BrandFull
    """
    db_order_detail = crud.get_order_detail_by_id(db, id_order_detail)
    if db_order_detail is None:
        Exceptions.register_not_found("Order Detail", id_order_detail)
    return db_order_detail


@order_detail.get("/", response_model=List[OrderDetail])
def get_order_details(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show order details

    This path operation shows a list of order details in the app with a limit on the number of order details.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of order details to retrieve (default: 10)

    Returns a JSON with a list of order details in the app.
    """
    return crud.get_order_details(db, skip=skip, limit=limit)


@order_detail.get("/full/", response_model=List[OrderDetailFull])
def get_order_details_full(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show order details full

    This path operation shows a list of order details full in the app with a limit on the number of order details full.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of order details full to retrieve (default: 10)

    Returns a JSON with a list of order details full in the app.
    """
    return crud.get_order_details(db, skip=skip, limit=limit)


@order_detail.post("/", response_model=OrderDetail)
def create_order_detail(order_detail: OrderDetailCreate, db: Session = Depends(get_db)):
    """
    Create an OrderDetail

    This path operation creates a new order_detail in the app.

    Parameters:
    - Request body parameter
        - order_detail: OrderDetailCreate -> A JSON object containing the following keys:
            - order_detail_number: str
            - order_detail_date: date
            - id_order: int

    Returns a JSON with the newly created order_detail:
    - id_order_detail: int
    - order_detail_number: str
    - order_detail_date: date
    - id_order: int
    """
    return crud.create_order_detail(db, order_detail)


@order_detail.post("/file/{id_order}/{type_format}")
async def create_order_details(id_order: int, type_format: str, details: UploadFile = File(...), db: Session = Depends(get_db)):
    if not details.filename.endswith(('xlsx', 'xlsm')):
        Exceptions.conflict_with_register('File Format', details.filename)
    if not type_format in [Constants.CHILD, Constants.DAME]:
        Exceptions.conflict_with_register('Type format', details.filename)
    result = await crud.create_order_details(db, id_order, type_format, details)
    if result:
        return {"message": "Orders detail to order was {id_order} created"}
    else:
        return Exceptions.conflict_with_register('File', details.filename)


@order_detail.put("/{id_order_detail}", response_model=OrderDetail)
def update_order_detail(id_order_detail: int, order_detail: OrderDetailCreate, db: Session = Depends(get_db)):
    """
    Update an OrderDetail

    This path operation updates an existing order_detail in the app.

    Parameters:
    - Register path parameter
        - id_order_detail: int
    - Request body parameter
        - order_detail: OrderDetailCreate -> A JSON object containing the updated order_detail data:
            - order_detail_number: str
            - order_detail_date: date
            - id_order: int

    Returns a JSON with the updated order_detail:
    - id_order_detail: int
    - order_detail_number: str
    - order_detail_date: date
    - id_order: int
    """
    db_order_detail = crud.update_order_detail(
        db, id_order_detail, order_detail)
    if db_order_detail is None:
        Exceptions.register_not_found("Order Detail", id_order_detail)
    return db_order_detail


@order_detail.delete("/{id_order_detail}")
def delete_order_detail(id_order_detail: int, db: Session = Depends(get_db)):
    """
    Delete an OrderDetail

    This path operation deletes an order_detail from the app.

    Parameters:
    - Register path parameter
        - id_order_detail: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_order_detail(db, id_order_detail)
    if not success:
        Exceptions.register_not_found("Order Detail", id_order_detail)
    return {"message": "OrderDetail deleted successfully"}


@order_detail.get("/by_brand/{id_order}", response_model=List[OrderDetailByBrand])
def get_order_detail_by_brand_and_id_order(id_order: int, db: Session = Depends(get_db)):
    result = crud.get_order_detail_by_brand_and_id_order(db, id_order)
    return result
