from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Entorno
    ENV: str
    PROJECT_NAME: str = "crm"

    # Configuración de base de datos
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int

    # JWT
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # CORS
    BACKEND_CORS_ORIGINS: str

    USERNAME: str
    CLIENT_ID: str
    CLIENT_SECRET: str
    TENANT_ID: str
    FRONTEND_URL: str

    class Config:
        env_file = ".env"  # Lee este archivo por defecto
        env_file_encoding = "utf-8"


settings = Settings()
