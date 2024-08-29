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


# VAlidate Relationships
try:
    configure_mappers()
    print("All mappers are configured correctly.")
except Exception as e:
    print(f"Error in mapper configuration: {e}")

app.include_router(customer)
app.include_router(user)
app.include_router(task)