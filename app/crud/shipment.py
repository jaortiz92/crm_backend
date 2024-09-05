# Python
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

# App
from app.models.shipment import Shipment as ShipmentModel
from app.schemas.shipment import ShipmentCreate, Shipment as ShipmentSchema


def create_shipment(db: Session, shipment: ShipmentCreate) -> ShipmentSchema:
    db_shipment = ShipmentModel(**shipment.model_dump())
    db.add(db_shipment)
    db.commit()
    db.refresh(db_shipment)
    return db_shipment


def get_shipment_by_id(db: Session, id_shipment: int) -> ShipmentSchema:
    result = db.query(ShipmentModel).filter(
        ShipmentModel.id_shipment == id_shipment).first()
    return result


def get_shipments(db: Session, skip: int = 0, limit: int = 10) -> list[ShipmentSchema]:
    return db.query(ShipmentModel).offset(skip).limit(limit).all()


def update_shipment(db: Session, id_shipment: int, shipment: ShipmentCreate) -> ShipmentSchema:
    db_shipment = db.query(ShipmentModel).filter(
        ShipmentModel.id_shipment == id_shipment).first()
    if db_shipment:
        for key, value in shipment.model_dump().items():
            setattr(db_shipment, key, value)
        db.commit()
        db.refresh(db_shipment)
    return db_shipment


def delete_shipment(db: Session, id_shipment: int):
    db_shipment = db.query(ShipmentModel).filter(
        ShipmentModel.id_shipment == id_shipment).first()
    if db_shipment:
        db.delete(db_shipment)
        db.commit()
        return True
    return False
