# Python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

# App
from app.schemas import CustomerSummary
from app import get_db
import app.crud as crud
from app.api.utils import Exceptions

query = APIRouter(
    prefix="/query",
    tags=["Query"],
)


@query.get("/customer_summary/{id_customer}", response_model=List[CustomerSummary])
def get_rating_by_id(id_customer: int, db: Session = Depends(get_db)):
    """
    Show a summary about custommer
    """
    db_rating = crud.get_customer_summary(db, id_customer)
    if db_rating is None:
        Exceptions.register_not_found("Custommer Summary", id_customer)
    return db_rating
