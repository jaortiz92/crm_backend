# Pydantic
from pydantic import BaseModel
from typing import Optional


class Summary(BaseModel):
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
        from_attributes = True


class BasicCollection(Summary):
    collection_name: str
    short_collection_name: str
    year: int
    quarter: int
    customer_trips: int


class CollectionSummary(BasicCollection):
    customers: int


class CustomerSummary(BasicCollection):
    id_collection: int
    id_customer: int


class CustomerTripSummary(Summary):
    id_customer_trip: int
    closed: bool


class CustomerValidationResult(BaseModel):
    document: float
    exists: bool
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    active: Optional[bool] = None
    seller: Optional[str] = None

    class Config:
        from_attributes = True

