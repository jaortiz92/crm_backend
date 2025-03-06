# FastApi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import configure_mappers

# App
from app.db import engine
from app.models import Base
from app.api import *


Base.metadata.create_all(bind=engine)


app = FastAPI(
    docs_url="/"
)

# CORS

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validate Relationships
try:
    configure_mappers()
    print("All mappers are configured correctly.")
except Exception as e:
    print(f"Error in mapper configuration: {e}")

app.include_router(activity)
app.include_router(activity_type)
app.include_router(advance)
app.include_router(brand)
app.include_router(city)
app.include_router(collection)
app.include_router(contact)
app.include_router(credit)
app.include_router(customer)
app.include_router(customer_trip)
app.include_router(department)
app.include_router(invoice)
app.include_router(invoice_detail)
app.include_router(line)
app.include_router(order)
app.include_router(order_detail)
app.include_router(payment_method)
app.include_router(rating)
app.include_router(rating_category)
app.include_router(role)
app.include_router(shipment)
app.include_router(store_type)
app.include_router(task)
app.include_router(user)
app.include_router(token)
app.include_router(photo)
app.include_router(query)
