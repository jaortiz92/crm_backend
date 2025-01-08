# Python
from sqlalchemy.orm import Session
from sqlalchemy import func, extract

# App
from app.models.query import CustomerSummary as CustomerSummaryModel


def get_customer_summary(db: Session, id_customer: int) -> list[CustomerSummaryModel]:
    result = db.query(CustomerSummaryModel).filter(
        CustomerSummaryModel.id_customer == id_customer
    ).all()
    return result
