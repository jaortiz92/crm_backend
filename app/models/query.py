# SQLalchemy
from sqlalchemy import (
    Column, Integer, Float,
    Text, Boolean
)
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class CustomerSummary(Base):
    __tablename__ = "customer_trip_summary_with_colletion"

    id = Column(Integer, primary_key=True)
    collection_name = Column(Text)
    short_collection_name = Column(Text)
    year = Column(Integer)
    quarter = Column(Integer)
    id_collection = Column(Integer)
    id_customer = Column(Integer)
    customer_trips = Column(Integer)
    budget = Column(Float)
    budget_quantities = Column(Integer)
    orders = Column(Integer)
    order_quantities = Column(Integer)
    order_without_tax = Column(Float)
    invoices = Column(Integer)
    invoice_quantities = Column(Integer)
    invoice_without_tax = Column(Float)
    invoice_discount = Column(Float)


class CustomerTripSummary(Base):
    __tablename__ = "customer_trip_summary_full"

    id_customer_trip = Column(Integer, primary_key=True)
    budget = Column(Float)
    budget_quantities = Column(Integer)
    ordered = Column(Boolean)
    orders = Column(Integer)
    order_quantities = Column(Integer)
    order_without_tax = Column(Float)
    invoices = Column(Integer)
    invoice_quantities = Column(Integer)
    invoice_without_tax = Column(Float)
    invoice_discount = Column(Float)
