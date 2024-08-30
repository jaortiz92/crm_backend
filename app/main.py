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


# Validate Relationships
try:
    configure_mappers()
    print("All mappers are configured correctly.")
except Exception as e:
    print(f"Error in mapper configuration: {e}")

app.include_router(customer)
app.include_router(user)
app.include_router(task)
app.include_router(activity)
app.include_router(activity_type)
app.include_router(customer_trip)
app.include_router(contact)
