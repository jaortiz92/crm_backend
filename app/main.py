# FastApi
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# App
from db import engine
from models import Base


Base.metadata.create_all(bind=engine)


app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
