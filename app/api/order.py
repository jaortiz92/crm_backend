# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Order, OrderCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

order = APIRouter(
    prefix="/order",
    tags=["Order"],
)

@order.get("/{id_order}", response_model=Order)
def get_order_by_id(id_order: int, db: Session = Depends(get_db)):
    """
    Show an Order

    This path operation shows an order in the app.

    Parameters:
    - Register path parameter
        - id_order: int

    Returns a JSON with the order:
    - id_order: int
    - id_customer_trip: int
    - id_seller: int
    - date_order: date
    - id_payment_method: int
    - quantities: int
    - system_quantities: Optional[int]
    - value_without_tax: int
    - value_with_tax: int
    - delivery_date: date
    """
    db_order = crud.get_order_by_id(db, id_order)
    if db_order is None:
        Exceptions.register_not_found("Order", id_order)
    return db_order

@order.get("/", response_model=List[Order])
def get_orders(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show orders

    This path operation shows a list of orders in the app with a limit on the number of orders.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of orders to retrieve (default: 10)

    Returns a JSON with a list of orders in the app.
    """
    return crud.get_orders(db, skip=skip, limit=limit)

@order.get("/customer/{id_customer}", response_model=List[Order])
def get_orders_by_id_customer(id_customer: int, db: Session = Depends(get_db)):
    """
    Show orders by customer

    This path operation shows a list of orders by customer in the app with a limit on the number of orders.

    Parameters:
    - Register path parameter
        - id_customer: int

    Returns a JSON with a list of orders in the app.
    """
    return crud.get_orders_by_id_customer(db, id_customer)

@order.post("/", response_model=Order)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    """
    Create an Order

    This path operation creates a new order in the app.

    Parameters:
    - Request body parameter
        - order: OrderCreate -> A JSON object containing the following keys:
            - id_customer_trip: int
            - id_seller: int
            - date_order: date
            - id_payment_method: int
            - quantities: int
            - system_quantities: Optional[int]
            - value_without_tax: int
            - value_with_tax: int
            - delivery_date: date

    Returns a JSON with the newly created order:
    - id_order: int
    - id_customer_trip: int
    - id_seller: int
    - date_order: date
    - id_payment_method: int
    - quantities: int
    - system_quantities: Optional[int]
    - value_without_tax: int
    - value_with_tax: int
    - delivery_date: date
    """
    db_order = crud.create_order(db, order)
    if isinstance(db_order, list):
        Exceptions.register_not_found(db_order[0], db_order[1])
    return db_order

@order.put("/{id_order}", response_model=Order)
def update_order(id_order: int, order: OrderCreate, db: Session = Depends(get_db)):
    """
    Update an Order

    This path operation updates an existing order in the app.

    Parameters:
    - Register path parameter
        - id_order: int
    - Request body parameter
        - order: OrderCreate -> A JSON object containing the updated order data:
            - id_customer_trip: int
            - id_seller: int
            - date_order: date
            - id_payment_method: int
            - quantities: int
            - system_quantities: Optional[int]
            - value_without_tax: int
            - value_with_tax: int
            - delivery_date: date

    Returns a JSON with the updated order:
    - id_order: int
    - id_customer_trip: int
    - id_seller: int
    - date_order: date
    - id_payment_method: int
    - quantities: int
    - system_quantities: Optional[int]
    - value_without_tax: int
    - value_with_tax: int
    - delivery_date: date
    """
    db_order = crud.update_order(db, id_order, order)
    if db_order is None:
        Exceptions.register_not_found("Order", id_order)
    elif isinstance(db_order, list):
        Exceptions.register_not_found(db_order[0], db_order[1])
    return db_order

@order.delete("/{id_order}")
def delete_order(id_order: int, db: Session = Depends(get_db)):
    """
    Delete an Order

    This path operation deletes an order from the app.

    Parameters:
    - Register path parameter
        - id_order: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_order(db, id_order)
    if not success:
        Exceptions.register_not_found("Order", id_order)
    return {"message": "Order deleted successfully"}
