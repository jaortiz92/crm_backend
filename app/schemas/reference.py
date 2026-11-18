# Python
from datetime import datetime
from typing import Optional, List

# Pydantic
from pydantic import BaseModel, Field

# App
from app.core import Gender


class ReferenceBase(BaseModel):
    reference: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description='Reference code (max 100 characters)'
    )
    id_brand: int = Field(
        ...,
        gt=0,
        description='ID of the brand'
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description='Reference description (max 500 characters)'
    )
    gender: Gender = Field(
        ...,
        description='Gender: U (0), M (1), F (2)'
    )
    value_base: float = Field(
        ...,
        ge=0,
        description='Base value (must be >= 0)'
    )
    id_collection: Optional[int] = Field(
        None,
        gt=0,
        description='ID of the collection (optional)'
    )


class ReferenceCreate(ReferenceBase):
    pass


class Reference(ReferenceBase):
    id_reference: int = Field(
        ...,
        gt=0
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BulkUploadResult(BaseModel):
    message: str
    total_filas: int
    insertadas: int
    actualizadas: int
    errores: List[str]


class BulkDeleteResult(BaseModel):
    message: str
    total_eliminadas: int
    referencias_eliminadas: List[str]
