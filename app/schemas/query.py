# Pydantic
from pydantic import BaseModel


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
