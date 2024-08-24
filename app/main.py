# FastApi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# App
from .db import engine, Base
from .models import *
from .api import *


Base.metadata.create_all(bind=engine)


app = FastAPI(
    docs_url="/"
)

app.include_router(user)
