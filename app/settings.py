from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import List, Union


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

    # BE-S11-COLLABORATORS (D-S11-7, OQ-BE-2): allow-list de role_names
    # para el dato confidencial del salario (Ley 1581/2012). Se parsean
    # EXACTAMENTE como BACKEND_CORS_ORIGINS: string CSV en .env -> lista
    # (los List[str] de pydantic-settings exigen JSON, no CSV). EMPTY
    # list = no configurada = cualquier usuario autenticado puede (el
    # endpoint lo documenta; la FE-S15 solo muestra mascaras cuando
    # salary_masked=true).
    COLLAB_VIEW_ROLES: Union[List[str], str] = []
    COLLAB_EDIT_ROLES: Union[List[str], str] = []

    @field_validator("COLLAB_VIEW_ROLES", "COLLAB_EDIT_ROLES", mode="before")
    @classmethod
    def _split_role_lists(cls, value):
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",")]
            return [p for p in parts if p]
        return value

    class Config:
        env_file = ".env"  # Lee este archivo por defecto
        env_file_encoding = "utf-8"


settings = Settings()
