from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json

info = open("./app/db/configdb.json")
info = json.load(info)
SQLALCHEMY_DATABASE_URL = f'postgresql://{info["user"]}:{info["pass"]}@{info["host"]}/{info["db"]}'

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()