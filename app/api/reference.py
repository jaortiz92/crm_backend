# Python
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import io

# App
from app.schemas import Reference, ReferenceCreate, BulkUploadResult, BulkDeleteResult
from app import get_db
from app.core.auth import get_current_user
import app.crud as crud
from app.api.utils import Exceptions

reference = APIRouter(
    prefix="/reference",
    tags=["Reference"],
)


@reference.get("/template")
def download_upload_template(
    current_user=Depends(get_current_user)
):
    """
    Download upload template

    This path operation generates and downloads an Excel template for bulk upload of references.

    Returns an Excel file with the required columns and example data.
    """
    template_bytes = crud.create_upload_template()
    
    return StreamingResponse(
        io.BytesIO(template_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=reference_upload_template.xlsx"}
    )


@reference.get("/template-delete")
def download_delete_template(
    current_user=Depends(get_current_user)
):
    """
    Download delete template

    This path operation generates and downloads an Excel template for bulk delete of references.

    Returns an Excel file with the required column and example data.
    """
    template_bytes = crud.create_delete_template()
    
    return StreamingResponse(
        io.BytesIO(template_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=reference_delete_template.xlsx"}
    )


@reference.get("/", response_model=List[Reference])
def get_references(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Show references

    This path operation shows a list of references in the app with a limit on the number of references.

    Parameters:
    - Query parameters:
        - skip: int - The number of records to skip (default: 0)
        - limit: int - The maximum number of references to retrieve (default: 10)

    Returns a JSON with a list of references in the app.
    """
    return crud.get_references(db, skip=skip, limit=limit)


@reference.get("/{id_reference}", response_model=Reference)
def get_reference(
    id_reference: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Show a reference

    This path operation shows a reference in the app.

    Parameters:
    - Register path parameter
        - id_reference: int

    Returns a JSON with the reference:
    - id_reference: int
    - reference: str
    - id_brand: int
    - description: Optional[str]
    - gender: Gender
    - value_base: float
    - id_collection: Optional[int]
    - created_at: datetime
    - updated_at: datetime
    """
    db_reference = crud.get_reference(db, id_reference)
    if db_reference is None:
        Exceptions.register_not_found("Reference", id_reference)
    return db_reference


@reference.post("/", response_model=Reference)
def create_reference(
    reference: ReferenceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Create a reference

    This path operation creates a new reference in the app.

    Parameters:
    - Request body parameter
        - reference: ReferenceCreate -> A JSON object containing the following keys:
            - reference: str (max 100 characters)
            - id_brand: int
            - description: Optional[str] (max 500 characters)
            - gender: Gender (U, M, F)
            - value_base: float (>= 0)
            - id_collection: Optional[int]

    Returns a JSON with the newly created reference.
    """
    return crud.create_reference(db, reference)


@reference.put("/{id_reference}", response_model=Reference)
def update_reference(
    id_reference: int,
    reference: ReferenceCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Update a reference

    This path operation updates an existing reference in the app.

    Parameters:
    - Register path parameter
        - id_reference: int
    - Request body parameter
        - reference: ReferenceCreate -> A JSON object containing the updated reference data

    Returns a JSON with the updated reference.
    """
    db_reference = crud.update_reference(db, id_reference, reference)
    if db_reference is None:
        Exceptions.register_not_found("Reference", id_reference)
    return db_reference


@reference.delete("/{id_reference}")
def delete_reference(
    id_reference: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Delete a reference

    This path operation deletes a reference from the app.

    Parameters:
    - Register path parameter
        - id_reference: int

    Returns a message confirming the deletion.
    """
    success = crud.delete_reference(db, id_reference)
    if not success:
        Exceptions.register_not_found("Reference", id_reference)
    return {"message": "Reference deleted successfully"}


@reference.post("/upload", response_model=BulkUploadResult)
async def upload_references(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Bulk upload references from Excel file

    This path operation processes an Excel file for bulk upsert of references.

    Parameters:
    - Request body (multipart/form-data):
        - file: Excel file with columns: Referencia, Marca, Descripción, Género, Valor Base, Colección

    Returns a JSON with the upload results:
    - message: str
    - total_filas: int
    - insertadas: int
    - actualizadas: int
    - errores: List[str]
    """
    return crud.bulk_upload_references(db, file)


@reference.post("/delete-bulk", response_model=BulkDeleteResult)
async def delete_references_bulk(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Bulk delete references from Excel file

    This path operation processes an Excel file for bulk delete of references.

    Parameters:
    - Request body (multipart/form-data):
        - file: Excel file with column: Referencia

    Returns a JSON with the delete results:
    - message: str
    - total_eliminadas: int
    - referencias_eliminadas: List[str]
    """
    return crud.bulk_delete_references(db, file)
