# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.contact import Contact as ContactModel
from app.schemas.contact import ContactCreate, Contact as ContactSchema


def get_contact_by_id(db: Session, id_contact: int) -> ContactSchema:
    return db.query(ContactModel).filter(ContactModel.id_contact == id_contact).first()


def get_contacts(db: Session, skip: int = 0, limit: int = 10) -> list[ContactSchema]:
    return db.query(ContactModel).offset(skip).limit(limit).all()


def get_contacts_by_id_customer(db: Session, id_customer) -> list[ContactSchema]:
    return db.query(ContactModel).filter(
        ContactModel.id_customer == id_customer
    ).order_by(
        ContactModel.id_contact.asc()
    ).all()


def create_contact(db: Session, contact: ContactCreate) -> ContactSchema:
    db_contact = ContactModel(**contact.model_dump())
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact


def update_contact(db: Session, id_contact: int, contact: ContactCreate) -> ContactSchema:
    db_contact = db.query(ContactModel).filter(
        ContactModel.id_contact == id_contact).first()
    if db_contact:
        for key, value in contact.model_dump().items():
            setattr(db_contact, key, value)
        db.commit()
        db.refresh(db_contact)
    return db_contact


def delete_contact(db: Session, id_contact: int) -> bool:
    db_contact = db.query(ContactModel).filter(
        ContactModel.id_contact == id_contact).first()
    if db_contact:
        db.delete(db_contact)
        db.commit()
        return True
    return False
