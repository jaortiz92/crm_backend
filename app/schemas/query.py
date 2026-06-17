# Pydantic
from pydantic import BaseModel
from typing import Optional
from datetime import date


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
    line_name: str


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


class OrderWithoutInvoice(BaseModel):
    id_order: int
    date_order: date
    delivery_date: date
    total_quantities: int
    total_with_tax: float
    company_name: str
    seller_name: str
    collection_name: str
    line_name: str
    id_customer_trip: int

    class Config:
        from_attributes = True


class InvoiceWithoutDetail(BaseModel):
    id_invoice: int
    invoice_number: str
    invoice_date: date
    total_quantities: float
    total_with_tax: float
    company_name: str
    seller_name: str
    collection_name: str
    line_name: str
    id_order: int

    class Config:
        from_attributes = True
