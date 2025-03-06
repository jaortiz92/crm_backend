# Python
from sqlalchemy.orm import Session

# App
from app.models.photo import Photo as PhotoModel
from app.schemas.photo import Photo as PhotoSchema, PhotoCreate


def get_photo_by_id(db: Session, id_photo: int) -> PhotoSchema:
    result = db.query(PhotoModel).filter(
        PhotoModel.id_photo == id_photo).first()
    return result


def get_photos(db: Session, skip: int = 0, limit: int = 10) -> list[PhotoSchema]:
    return db.query(PhotoModel).offset(skip).limit(limit).all()


def get_photo_by_customer(db: Session, id_customer: str) -> PhotoSchema:
    result = db.query(PhotoModel).filter(
        PhotoModel.id_customer == id_customer).all()
    return result


def create_photo(db: Session, photo: PhotoCreate) -> PhotoSchema:
    db_photo = PhotoModel(**photo.model_dump())
    db.add(db_photo)
    db.commit()
    db.refresh(db_photo)
    return db_photo


def update_photo(db: Session, id_photo: int, photo: PhotoCreate) -> PhotoSchema:
    db_photo = db.query(PhotoModel).filter(
        PhotoModel.id_photo == id_photo).first()
    if db_photo:
        for key, value in photo.model_dump().items():
            setattr(db_photo, key, value)
        db.commit()
        db.refresh(db_photo)
    return db_photo


def delete_photo(db: Session, id_photo: int) -> bool:
    db_photo = db.query(PhotoModel).filter(
        PhotoModel.id_photo == id_photo).first()
    if db_photo:
        db.delete(db_photo)
        db.commit()
        return True
    return False
