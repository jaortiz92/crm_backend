# Pydantic
from pydantic import BaseModel


class CustomerSummary(BaseModel):
    collection_name: str
    short_collection_name: str
    year: int
    quarter: int
    id_collection: int
    id_customer: int
    customer_trips: int
    budget: float
    budget_quantities: int
    orders: int
    order_quantities: int
    order_without_tax: float
    invoices: int
    invoice_quantities: int
    invoice_without_tax: float
    invoice_discount: float

    class Config:
        orm_mode = True
