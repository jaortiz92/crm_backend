# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import Contact, ContactCreate
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

contact = APIRouter(
    prefix="/contact",
    tags=["Contact"],
)


@contact.get("/{id_contact}", response_model=Contact)
def get_contact_by_id(id_contact: int, db: Session = Depends(get_db)):
    """
    Show a Contact

    This path operation shows a contact in the app.

    Parameters:
    - Register path parameter
        - id_contact: int

    Returns a JSON with the contact:
    - id_contact: int
    - id_customer: int
    - first_name: str
    - last_name: str
    - document: float
    - gender: Gender
    - email: Optional[EmailStr]
    - phone: Optional[str]
    - id_role: int
    - birth_date: Optional[date]
    - id_city: int
    - active: bool
    """
    db_contact = crud.get_contact_by_id(db, id_contact)
    if db_contact is None:
        Exceptions.register_not_found("Contact", id_contact)
    return db_contact


@contact.get("/", response_model=List[Contact])
def get_contacts(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    """
    Show contacts

    This path operation shows a list of contacts in the app with a limit on the number of contacts.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of contacts to retrieve (default: 10)

    Returns a JSON with a list of contacts in the app.
    """
    return crud.get_contacts(db, skip=skip, limit=limit)


@contact.get("/customer/{id_customer}", response_model=List[Contact])
def get_contacts_by_id_customer(id_customer: int, db: Session = Depends(get_db)):
    """
    Show contacts by customer

    This path operation shows a list of contacts by customer in the app with a limit on the number of contacts.

    Parameters:
    - Register path parameter
        - id_customer: int

    Returns a JSON with a list of contacts in the app.
    """
    return crud.get_contacts_by_id_customer(db, id_customer)


@contact.post("/", response_model=Contact)
def create_contact(contact: ContactCreate, db: Session = Depends(get_db)):
    """
    Create a Contact

    This path operation creates a new contact in the app.

    Parameters:
    - Request body parameter
        - contact: ContactCreate -> A JSON object containing the following keys:
            - id_customer: int
            - first_name: str
            - last_name: str
            - document: float
            - gender: Gender
            - email: Optional[EmailStr]
            - phone: Optional[str]
            - id_role: int
            - birth_date: Optional[date]
            - id_city: int
            - active: bool

    Returns a JSON with the newly created contact:
    - id_customer: int
    - id_client: int
    - first_name: str
    - last_name: str
    - document: float
    - gender: Gender
    - email: Optional[EmailStr]
    - phone: Optional[str]
    - id_role: int
    - birth_date: Optional[date]
    - id_city: int
    - active: bool
    """
    return crud.create_contact(db, contact)


@contact.put("/{id_contact}", response_model=Contact)
def update_contact(id_contact: int, contact: ContactCreate, db: Session = Depends(get_db)):
    """
    Update a Contact

    This path operation updates an existing contact in the app.

    Parameters:
    - Register path parameter
        - id_contact: int
    - Request body parameter
        - contact: ContactCreate -> A JSON object containing the updated contact data:
            - id_customer: int
            - first_name: str
            - last_name: str
            - document: float
            - gender: Gender
            - email: Optional[EmailStr]
            - phone: Optional[str]
            - id_role: int
            - birth_date: Optional[date]
            - id_city: int
            - active: bool

    Returns a JSON with the updated contact:
    - id_contact: int
    - id_customer: int
    - first_name: str
    - last_name: str
    - document: float
    - gender: Gender
    - email: Optional[EmailStr]
    - phone: Optional[str]
    - id_role: int
    - birth_date: Optional[date]
    - id_city: int
    - active: bool
    """
    db_contact = crud.update_contact(db, id_contact, contact)
    if db_contact is None:
        Exceptions.register_not_found("Contact", id_contact)
    return db_contact


@contact.delete("/{id_contact}")
def delete_contact(id_contact: int, db: Session = Depends(get_db)):
    """
    Delete a Contact

    This path operation deletes a contact from the app.

    Parameters:
    - Register path parameter
        - id_contact: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_contact(db, id_contact)
    if not success:
        Exceptions.register_not_found("Contact", id_contact)
    return {"message": "Contact deleted successfully"}
