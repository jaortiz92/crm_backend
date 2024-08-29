# Python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Customer, CustomerCreate
from app import get_db
import app.crud as crud

customer = APIRouter(
    prefix="/customer",
    tags=["Customer"],
)

@customer.get("/{id_customer}", response_model=Customer)
def get_customer(id_customer: int, db: Session = Depends(get_db)):
    """
    Show a Customer

    This path operation shows a customer in the app

    Parameters:
    - Register path parameter
        - id_customer: int

    Returns a JSON with a customer in the app:
    - id_Customer: int
    - company_name: str
    - document: float
    - email: EmailStr
    - phone: Optional[str]
    - id_store_type: int
    - address: str
    - id_brand: int
    - id_seller: int
    - stores: int
    - id_city: int
    - active: bool
    """
    db_customer = crud.get_customer_by_id(db, id_customer)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return db_customer

@customer.get("/", response_model=List[Customer])
def get_customers(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show customers

    This path operation shows a list of customers in the app with a limit on the number of customers.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of customers to retrieve (default: 10)

    Returns a JSON with a list of customers in the app.
    """
    return crud.get_customers(db, skip=skip, limit=limit)

@customer.post("/", response_model=Customer)
def create_customer(customer: CustomerCreate, db: Session = Depends(get_db)):
    """
    Create a Customer

    This path operation creates a new customer in the app

    Parameters:
    - Request body parameter
        - customer: CustomerCreate -> A JSON object containing the following keys:
            - company_name: str
            - document: float
            - email: EmailStr
            - phone: Optional[str]
            - id_store_type: int
            - address: str
            - id_brand: int
            - id_seller: int
            - stores: int
            - id_city: int
            - active: bool

    Returns a JSON with the newly created customer:
    - id_Customer: int
    - company_name: str
    - document: float
    - email: EmailStr
    - phone: Optional[str]
    - id_store_type: int
    - address: str
    - id_brand: int
    - id_seller: int
    - stores: int
    - id_city: int
    - active: bool
    """
    return crud.create_customer(db, customer)


@customer.put("/{id_customer}", response_model=Customer)
def update_customer(id_customer: int, customer: CustomerCreate, db: Session = Depends(get_db)):
    """
    Update a Customer

    This path operation updates an existing customer in the app

    Parameters:
    - Register path parameter
        - id_customer: int
    - Request body parameter
        - customer: CustomerCreate -> A JSON object containing the updated customer data:
            - company_name: str
            - document: float
            - email: EmailStr
            - phone: Optional[str]
            - id_store_type: int
            - address: str
            - id_brand: int
            - id_seller: int
            - stores: int
            - id_city: int
            - active: bool

    Returns a JSON with the updated customer:
    - id_Customer: int
    - company_name: str
    - document: float
    - email: EmailStr
    - phone: Optional[str]
    - id_store_type: int
    - address: str
    - id_brand: int
    - id_seller: int
    - stores: int
    - id_city: int
    - active: bool
    """
    db_customer = crud.update_customer(db, id_customer, customer)
    if db_customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return db_customer

@customer.delete("/{id_customer}")
def delete_customer(id_customer: int, db: Session = Depends(get_db)):
    """
    Delete a Customer

    This path operation deletes a customer from the app

    Parameters:
    - Register path parameter
        - id_customer: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_customer(db, id_customer)
    if not success:
        raise HTTPException(
            status_code=404, 
            detail=f"Customer id:{id_customer} not found"
        )
    return {"message": "Customer deleted successfully"}
