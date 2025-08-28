from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from app.settings import settings

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=20,        # Número mínimo de conexiones
    max_overflow=40,     # Número de conexiones adicionales permitidas
    pool_timeout=40,     # Tiempo de espera para una conexión libre
    pool_pre_ping=True   # Para verificar que la conexión está viva
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
