# Especificación Técnica: ETL actual-expenses (Gastos Operativos Reales)

## 1. Objetivo del Proceso

Establecer la tubería ETL (Extract, Transform, Load) para procesar el archivo LibroAuxiliarCECO.xlsx e insertar los datos de gastos operativos en la tabla actual_expenses. Este pipeline capturará los gastos puros (arriendos, nómina, servicios, etc.) manteniendo la estrategia de reemplazo atómico consistente con el módulo de costos existente.

## 2. Estructura de Datos de Entrada

### 2.1 Archivo Fuente
- **Nombre del archivo**: LibroAuxiliarCECO.xlsx
- **Formato**: Excel (.xlsx)
- **Header**: Fila 4 (header=3 en pandas, índice 0-based)
- **Codificación**: UTF-8

### 2.2 Columnas del Excel
| Columna | Tipo de Dato | Descripción |
|---------|--------------|-------------|
| CentroCostos | String (object) | Código/nombre del centro de costos |
| CuentaContable | String (object) | Cuenta contable + concepto separados por espacio |
| Cuenta Tercero | String (object) | Información del tercero asociado |
| Fecha | datetime64[ns] | Fecha del movimiento |
| Notas | String (object) | Descripción/notas del movimiento |
| ChequeNumero | Float64 | Número de cheque (opcional) |
| NumDoc | String (object) | Número de comprobante/factura |
| Débitos | Float64 | Monto del débito |
| Créditos | Float64 | Monto del crédito |
| Saldos | Float64 | Saldo acumulado (no se usa) |

## 3. Flujo de Ejecución (Execution Pipeline)

El método de carga se estructura en 4 fases secuenciales dentro de una única transacción de base de datos. El pipeline se implementa como métodos de la clase `BudgetTemplates` (en `app/utils/templates/budgetTemplates.py`), siguiendo el mismo patrón arquitectónico que `process_cost()` + `_map_relational_data()` + `_validate_data_integrity()` + `_handle_duplicate_documents()` + `_bulk_insert()` usado para ActualCost.

### 3.1 Fase A: Limpieza de Datos (Data Cleansing)

**Método**: `BudgetTemplates.process_actual_expenses() -> DataFrame`

**Objetivo**: Preparar y filtrar los datos crudos del Excel.

**Pasos**:
1. **Cargar Excel**: Leer el archivo usando `pd.read_excel(self.file, engine="openpyxl", header=3)`
2. **Capturar total filas crudas**: Guardar `total_rows_raw = len(self.df)` antes de filtrar (para la respuesta)
3. **Eliminar filas sin documento**: Excluir todas las filas donde NumDoc sea nulo/vacío
4. **Excluir filas "Total"**: Eliminar filas donde CuentaContable contenga la palabra "Total" (ej: "Total 11050501 CAJA GENERAL")
5. **Filtrar solo gastos**: Conservar únicamente las filas donde CuentaContable comience con "5"
6. **Calcular monto neto**: Crear campo amount = Débitos - Créditos (puede ser negativo para notas de crédito)
7. **Estandarizar fechas**: Convertir columna Fecha al tipo DATE de PostgreSQL
8. **Validar tipos numéricos**: Asegurar que Débitos y Créditos sean valores numéricos válidos

**Resultado**: DataFrame limpio con solo registros de gastos válidos.

### 3.2 Fase B: Mapeo Relacional (Data Mapping)

**Método**: `BudgetTemplates._map_actual_expenses_relational_data(db: Session) -> DataFrame`

**Objetivo**: Transformar los datos del Excel a la estructura de la base de datos.

**Mapeo de campos**:

| Campo Excel | Campo BD | Transformación |
|-------------|----------|----------------|
| CentroCostos | id_cost_center | Cruzar con catálogo cost_center_code para obtener id_cost_center |
| CuentaContable | accounting_account | Extraer primera parte antes del primer espacio (ej: "51402001") |
| CuentaContable | expense_type | Extraer todo después del primer espacio (ej: "ADUANEROS") |
| Notas | description | Copiar directamente el contenido |
| NumDoc | document_number | Copiar directamente el número de comprobante |
| Fecha | expense_date | Convertir a tipo DATE |
| Débitos - Créditos | amount | Calcular diferencia (puede ser negativo) |
| Cuenta Tercero | third_party_account | Copiar directamente la información del tercero |

**Reglas de mapeo**:
- **accounting_account**: Extraer solo los dígitos iniciales antes del primer espacio en blanco
- **expense_type**: Extraer el texto después del primer espacio, eliminando espacios extras
- **amount**: Calcular como Débitos - Créditos, preservar valores negativos (notas de crédito, ajustes)

### 3.3 Fase C: Validaciones y Reemplazo (Safety & Upsert)

**Método**: `BudgetTemplates._validate_actual_expenses_integrity(db: Session) -> None`

**Objetivo**: Garantizar integridad referencial y evitar duplicados.

**Validaciones**:

1. **Validación de Centros de Costos**:
   - Extraer todos los valores únicos de CentroCostos del DataFrame
   - Verificar que cada código exista en la tabla de centros de costos (cost_center_code)
   - **Si algún código no existe**: Rechazar TODO el archivo (rollback completo) lanzando `HTTPException(status_code=400)` con mensaje detallado indicando qué códigos no existen
   
2. **Fallback para CentroCostos vacío**:
   - Si CentroCostos está vacío, asignar centro de costos por defecto basado en el prefijo de accounting_account:
     - Inicia con "51" → usar código 410100
     - Inicia con "52" → usar código 210700
     - Inicia con "53" → usar código 510100
     - Inicia con "54" → usar código 999100
   - Validar que estos códigos de respaldo existan en la base de datos

3. **Validación de integridad de datos**:
   - Verificar que todas las fechas sean válidas
   - Verificar que amount sea un valor numérico válido
   - Si alguna validación falla, rechazar todo el archivo (rollback)

**Reemplazo Atómico**:

**Método**: `BudgetTemplates._handle_actual_expense_duplicates(db: Session) -> int`

- Antes de insertar nuevos registros, eliminar todos los registros existentes en actual_expenses que tengan los mismos document_number que los registros a insertar
- Esta eliminación ocurre dentro de la misma transacción que la inserción
- Contar el número de registros eliminados para la respuesta
- **NO hacer commit aquí** (el commit lo maneja el caller, consistente con `_handle_duplicate_documents()` de ActualCost)

### 3.4 Fase D: Inserción Masiva (Bulk Insert)

**Método**: `BudgetTemplates._bulk_insert_actual_expenses(db: Session, source_filename: str) -> list`

**Objetivo**: Insertar eficientemente todos los registros validados.

**Pasos**:
1. **Convertir a esquemas**: Transformar cada fila del DataFrame a instancias del esquema Pydantic ActualExpenseCreate
2. **Bulk insert**: Ejecutar inserción masiva usando `crud.create_actual_expenses_bulk(db, records)`
3. **Confirmar transacción**: El commit lo maneja `create_actual_expenses_bulk` internamente
4. **Manejo de errores**: Si cualquier error ocurre durante la inserción, ejecutar rollback() para revertir toda la transacción (delete + insert)

**Resultado**: Todos los registros insertados exitosamente en la tabla actual_expenses.

## 4. Estructura de la Tabla actual_expenses

### 4.1 Campos Existentes (ya en la base de datos)

| Campo | Tipo | Nullable | Descripción |
|-------|------|----------|-------------|
| id_actual_expense | Integer | No | Primary key auto-incremental |
| id_cost_center | Integer | No | Foreign key a cost_centers.id_cost_center |
| expense_date | Date | No | Fecha del gasto |
| expense_type | String(60) | No | Tipo de gasto/concepto (ej: "ADUANEROS") |
| description | Text | Sí | Descripción/notas del gasto |
| amount | Float | No | Monto del gasto (server_default="0") |
| source_file | String(200) | Sí | Nombre del archivo Excel fuente |
| created_at | DateTime | No | Timestamp de creación (auto-generado) |

### 4.2 Campos Nuevos a Agregar (ALTER TABLE)

| Campo | Tipo | Nullable | Descripción |
|-------|------|----------|-------------|
| accounting_account | String(20) | No | Código de cuenta contable (ej: "51402001") |
| document_number | String(50) | No | Número de comprobante/factura |
| third_party_account | Text | Sí | Información del tercero asociado |
| updated_at | DateTime | Sí | Timestamp de actualización (auto-generado con onupdate) |

### 4.3 Migración SQL (ejecutar manualmente o vía create_all si tabla no existe)

```sql
ALTER TABLE actual_expenses
    ADD COLUMN accounting_account VARCHAR(20) NOT NULL DEFAULT '',
    ADD COLUMN document_number VARCHAR(50) NOT NULL DEFAULT '',
    ADD COLUMN third_party_account TEXT,
    ADD COLUMN updated_at TIMESTAMP;
```

> **Nota**: Dado que el proyecto usa `Base.metadata.create_all()` y no Alembic, si la tabla ya existe con datos, se debe ejecutar el ALTER TABLE manualmente. Si la tabla se puede recrear desde cero, actualizar el modelo y reiniciar la app es suficiente.

### 4.4 Relaciones
- **id_cost_center**: Foreign key → cost_centers.id_cost_center (ya existe)

## 5. Endpoints a Implementar

### 5.1 POST /budget/upload/actual-expenses (Endpoint Existente - Stub a Implementar)

**Archivo**: `app/api/budget/upload.py` (líneas 38-49, actualmente con TODO)

**Descripción**: Endpoint principal para cargar el archivo de gastos operativos. Ya existe como stub, solo necesita implementación.

**Request**:
- **Content-Type**: multipart/form-data
- **Body**: Archivo Excel (LibroAuxiliarCECO.xlsx)
- **Autenticación**: JWT Bearer token requerido

**Response Exitoso (HTTP 200)**:
```json
{
  "message": "Actual expenses uploaded successfully",
  "records_inserted": 2733,
  "records_replaced": 150,
  "source_file": "LibroAuxiliarCECO.xlsx",
  "details": {
    "total_rows_processed": 10391,
    "rows_filtered": 7658,
    "valid_expenses": 2733
  }
}
```

**Response de Error (HTTP 400)**:
```json
{
  "detail": "Cost centers not found in catalog: ['Centro Inexistente 1', 'Centro Inexistente 2']"
}
```

**Lógica del endpoint** (a implementar en `upload.py`):
```python
@router.post("/actual-expenses")
async def upload_actual_expenses(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        etl = BudgetTemplates(file_bytes)
        
        # Fase A: Limpieza
        df = etl.process_actual_expenses()
        total_rows_raw = etl.total_rows_raw
        
        # Fase B: Mapeo relacional
        etl._map_actual_expenses_relational_data(db)
        
        # Fase C: Validaciones
        etl._validate_actual_expenses_integrity(db)
        
        # Fase C (cont.): Reemplazo atómico
        records_deleted = etl._handle_actual_expense_duplicates(db)
        
        # Fase D: Bulk insert
        inserted_records = etl._bulk_insert_actual_expenses(db, file.filename)

        return {
            "message": "Actual expenses uploaded successfully",
            "records_inserted": len(inserted_records),
            "records_replaced": records_deleted,
            "source_file": file.filename,
            "details": {
                "total_rows_processed": total_rows_raw,
                "rows_filtered": total_rows_raw - len(df),
                "valid_expenses": len(df)
            }
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing actual expenses: {str(e)}"
        )
```

### 5.2 DELETE /budget/actual-expense/by-document/{document_number} (Endpoint Nuevo)

**Archivo**: `app/api/budget/actualExpense.py` (agregar al archivo existente)

**Descripción**: Eliminar todos los registros asociados a un comprobante específico.

**Path Parameters**:
- document_number: String - Número del comprobante a eliminar (ej: "FC FE 2530")

**Request**:
- **Autenticación**: JWT Bearer token requerido

**Response Exitoso (HTTP 200)**:
```json
{
  "message": "Actual expenses deleted successfully",
  "records_deleted": 5,
  "document_number": "FC FE 2530"
}
```

**Response de Error (HTTP 404)**:
Usar `Exceptions.register_not_found("ActualExpense", document_number)` si no hay registros.

**Lógica del endpoint** (a agregar en `actualExpense.py`):
```python
@router.delete("/by-document/{document_number}")
def delete_actual_expense_by_document(
    document_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Eliminar registros por número de documento."""
    deleted_count = crud.delete_actual_expenses_by_document(db, document_number)
    
    if deleted_count == 0:
        Exceptions.register_not_found("ActualExpense", document_number)
    
    return {
        "message": "Actual expenses deleted successfully",
        "records_deleted": deleted_count,
        "document_number": document_number
    }
```

## 6. Archivos a Modificar (Backend)

> **IMPORTANTE**: El módulo `actualExpense` ya existe dentro del paquete `budget/`. No se crean archivos nuevos, se **modifican** los existentes.

### 6.1 Modelo (app/models/budget/actualExpense.py) - MODIFICAR

**Estado actual**: Modelo existe con campos básicos (id_actual_expense, id_cost_center, expense_date, expense_type, description, amount, source_file, created_at).

**Cambios requeridos**:
- Agregar campos: `accounting_account`, `document_number`, `third_party_account`, `updated_at`
- Mantener PK como `id_actual_expense` (NO cambiar a `id`)
- Mantener FK como `ForeignKey("cost_centers.id_cost_center")` (NO `cost_centers.id`)
- Mantener `source_file` (campo existente)
- Mantener relación `cost_center`
- Cambiar tipo de `amount` de `Float` a `Numeric(15, 2)` para precisión contable

**Modelo resultante**:
```python
from sqlalchemy import Column, ForeignKey, Float, Integer, String, Numeric, Date, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class ActualExpense(Base):
    __tablename__ = "actual_expenses"

    id_actual_expense = Column(Integer, primary_key=True, index=True)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    accounting_account = Column(String(20), nullable=False, server_default="")
    expense_date = Column(Date, nullable=False)
    expense_type = Column(String(60), nullable=False)
    description = Column(Text)
    amount = Column(Numeric(15, 2), nullable=False, server_default="0")
    document_number = Column(String(50), nullable=False, server_default="")
    third_party_account = Column(Text, nullable=True)
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    cost_center = relationship("CostCenter", back_populates="actual_expenses")
```

**Registro**: Ya registrado en `app/models/budget/__init__.py` línea 2. No se requiere cambio.

### 6.2 Esquemas (app/schemas/budget/actualExpense.py) - MODIFICAR

**Estado actual**: Schema existe con campos básicos. `amount` tiene restricción `ge=0` que impide valores negativos.

**Cambios requeridos**:
- Agregar campos: `accounting_account`, `document_number`, `third_party_account`
- Eliminar restricción `ge=0` del campo `amount` (permitir negativos para notas de crédito)
- Agregar schemas de respuesta para upload y delete
- Mantener `source_file`

**Schemas resultantes**:
```python
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class ActualExpenseBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    accounting_account: str = Field(..., max_length=20, description="Accounting account code")
    expense_date: date = Field(..., description="Date of the expense")
    expense_type: str = Field(..., max_length=60, description="Category of expense")
    description: Optional[str] = Field(None, description="Detail of the expense")
    amount: float = Field(..., description="Expense amount (negative for credit notes)")
    document_number: str = Field(..., max_length=50, description="Document/voucher number")
    third_party_account: Optional[str] = Field(None, description="Third party account info")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")


class ActualExpenseCreate(ActualExpenseBase):
    pass


class ActualExpense(ActualExpenseBase):
    id_actual_expense: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

**Registro**: Ya registrado en `app/schemas/budget/__init__.py` línea 2. No se requiere cambio.

### 6.3 CRUD (app/crud/budget/actualExpense.py) - MODIFICAR

**Estado actual**: CRUD existe con funciones básicas (create, bulk, get, update, delete by ID).

**Funciones a agregar**:
```python
def delete_actual_expenses_by_document(db: Session, document_number: str) -> int:
    """Eliminar todos los registros con un document_number específico."""
    count = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.document_number == document_number
    ).delete(synchronize_session=False)
    db.commit()
    return count


def delete_actual_expenses_by_documents(
    db: Session, document_numbers: List[str]
) -> int:
    """Eliminar registros por lista de document_numbers (para reemplazo atómico).
    NO hace commit - el caller controla la transacción."""
    count = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.document_number.in_(document_numbers)
    ).delete(synchronize_session=False)
    return count
```

**Registro**: Ya registrado en `app/crud/budget/__init__.py` línea 2 (`from .actualExpense import *`). No se requiere cambio.

**Patrón de acceso**: Las funciones se acceden vía `crud.delete_actual_expenses_by_document(db, doc)` (NO `crud.actualExpense.func()`).

### 6.4 API - Upload (app/api/budget/upload.py) - MODIFICAR

**Estado actual**: Endpoint stub en líneas 38-49 con `TODO: Implement ETL processing`.

**Cambio**: Reemplazar el stub con la implementación completa (ver Sección 5.1).

**Registro**: Ya registrado en `app/api/budget/__init__.py` línea 19 y montado con `prefix="/upload"` en línea 54. No se requiere cambio.

### 6.5 API - Actual Expense (app/api/budget/actualExpense.py) - MODIFICAR

**Estado actual**: API CRUD completa existe. Falta endpoint DELETE by document_number.

**Cambio**: Agregar endpoint DELETE `/by-document/{document_number}` (ver Sección 5.2).

**Registro**: Ya registrado en `app/api/budget/__init__.py` línea 10 y montado con `prefix="/actual-expense"` en línea 25. No se requiere cambio.

### 6.6 Servicio ETL (app/utils/templates/budgetTemplates.py) - MODIFICAR

**Estado actual**: Clase `BudgetTemplates` existe con método stub `process_libro_auxiliar_ceco()` (líneas 427-445) que es un placeholder genérico.

**Cambios requeridos**:
- Reemplazar `process_libro_auxiliar_ceco()` con `process_actual_expenses()` que implemente la Fase A completa
- Agregar método `_map_actual_expenses_relational_data(db)` para Fase B
- Agregar método `_validate_actual_expenses_integrity(db)` para Fase C
- Agregar método `_handle_actual_expense_duplicates(db)` para reemplazo atómico
- Agregar método `_bulk_insert_actual_expenses(db, source_filename)` para Fase D

**Métodos a agregar en BudgetTemplates**:

```python
# ──────────────────────────────────────────────
# LibroAuxiliarCECO.xlsx -> Actual Expenses
# ──────────────────────────────────────────────

def process_actual_expenses(self) -> DataFrame:
    """
    Process LibroAuxiliarCECO.xlsx for actual expense records.

    Steps:
    1. Read Excel with header=3
    2. Drop rows without NumDoc
    3. Exclude rows with "Total" in CuentaContable
    4. Filter only expenses (CuentaContable starts with "5")
    5. Calculate amount = Débitos - Créditos
    6. Cast numeric and date columns

    Returns:
        DataFrame with cleaned and transformed data
    """
    self.df = pd.read_excel(
        self.file,
        engine="openpyxl",
        header=3,
    )
    self.total_rows_raw = len(self.df)

    # Drop rows without document number
    self.df.dropna(subset=['NumDoc'], inplace=True)
    self.df = self.df[self.df['NumDoc'].astype(str).str.strip() != '']

    # Exclude "Total" rows
    self.df = self.df[
        ~self.df['CuentaContable'].astype(str).str.contains('Total', case=False, na=False)
    ]

    # Filter only expenses (CuentaContable starts with "5")
    self.df = self.df[
        self.df['CuentaContable'].astype(str).str.startswith('5')
    ]

    # Calculate net amount
    self.df['amount'] = (
        pd.to_numeric(self.df['Débitos'], errors='coerce').fillna(0)
        - pd.to_numeric(self.df['Créditos'], errors='coerce').fillna(0)
    )

    # Extract accounting_account and expense_type from CuentaContable
    cuenta_split = self.df['CuentaContable'].astype(str).str.split(' ', n=1)
    self.df['accounting_account'] = cuenta_split.str[0].str.strip()
    self.df['expense_type'] = cuenta_split.str.get(1, '').str.strip()

    # Cast dates
    self.df['expense_date'] = pd.to_datetime(
        self.df['Fecha'], errors='coerce'
    ).dt.date

    # Standardize text fields
    self.df['document_number'] = self.df['NumDoc'].astype(str).str.strip()
    self.df['description'] = self.df['Notas'].where(
        self.df['Notas'].notna(), None
    )
    self.df['third_party_account'] = self.df['Cuenta Tercero'].where(
        self.df['Cuenta Tercero'].notna(), None
    )
    self.df['centro_costos_raw'] = self.df['CentroCostos'].astype(str).str.strip()

    return self.df

def _map_actual_expenses_relational_data(self, db: Session) -> DataFrame:
    """
    Map CentroCostos codes to id_cost_center FK.
    Applies fallback rules for empty CentroCostos.
    """
    # Load cost center map: code -> id
    cost_centers = db.query(CostCenterModel).all()
    code_to_id = {cc.cost_center_code: cc.id_cost_center for cc in cost_centers}

    # Fallback for empty CentroCostos based on accounting_account prefix
    fallback_map = {
        '51': '410100',
        '52': '210700',
        '53': '510100',
        '54': '999100',
    }

    def resolve_cost_center(row):
        cc_raw = row['centro_costos_raw']
        if cc_raw == '' or cc_raw == 'nan' or pd.isna(row['CentroCostos']):
            prefix = row['accounting_account'][:2]
            return fallback_map.get(prefix, None)
        return cc_raw

    self.df['cost_center_code'] = self.df.apply(resolve_cost_center, axis=1)
    self.df['id_cost_center'] = self.df['cost_center_code'].map(code_to_id)

    return self.df

def _validate_actual_expenses_integrity(self, db: Session) -> None:
    """
    Validate data integrity before insertion:
    1. Check all cost center codes exist in catalog
    2. Validate dates and amounts
    """
    from fastapi import HTTPException, status as http_status

    # 1. Missing cost centers
    missing_cc = self.df[self.df['id_cost_center'].isna()]
    if not missing_cc.empty:
        invalid_codes = missing_cc['cost_center_code'].unique().tolist()
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Cost centers not found in catalog: {invalid_codes}"
        )

    # 2. Invalid dates
    invalid_dates = self.df[self.df['expense_date'].isna()]
    if not invalid_dates.empty:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{len(invalid_dates)} records have invalid dates"
        )

def _handle_actual_expense_duplicates(self, db: Session) -> int:
    """
    Detect if any document_number in the new file already exists in DB.
    If duplicates found, delete all existing records with those document_numbers.

    This deletion runs within the same transaction as the subsequent bulk insert.
    If the bulk insert fails, a rollback will restore the deleted records.

    Returns:
        Number of records deleted (0 if no duplicates)
    """
    from app.models.budget.actualExpense import ActualExpense as ActualExpenseModel

    new_document_numbers = self.df['document_number'].unique().tolist()

    existing_count = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.document_number.in_(new_document_numbers)
    ).count()

    if existing_count == 0:
        return 0

    deleted_count = db.query(ActualExpenseModel).filter(
        ActualExpenseModel.document_number.in_(new_document_numbers)
    ).delete(synchronize_session=False)

    return deleted_count

def _bulk_insert_actual_expenses(self, db: Session, source_filename: str) -> list:
    """
    Convert DataFrame to ActualExpenseCreate records and perform bulk insert.
    Transaction is atomic (all-or-nothing).
    """
    from app.schemas.budget import ActualExpenseCreate

    records = []
    for _, row in self.df.iterrows():
        records.append(ActualExpenseCreate(
            id_cost_center=int(row['id_cost_center']),
            accounting_account=str(row['accounting_account']),
            expense_type=str(row['expense_type']),
            description=row.get('description'),
            amount=float(row['amount']),
            document_number=str(row['document_number']),
            expense_date=row['expense_date'],
            third_party_account=row.get('third_party_account'),
            source_file=source_filename,
        ))

    return crud.create_actual_expenses_bulk(db, records)
```

**Registro**: No aplica — es un método nuevo en clase existente.

## 7. Criterios de Aceptación

### 7.1 Criterios Funcionales
- [ ] El sistema carga exitosamente el archivo LibroAuxiliarCECO.xlsx
- [ ] Se filtran correctamente solo las filas con CuentaContable que inicia con "5"
- [ ] Se excluyen filas con NumDoc vacío y filas con "Total" en CuentaContable
- [ ] El campo amount se calcula correctamente como Débitos - Créditos
- [ ] Los valores negativos (notas de crédito) se preservan correctamente
- [ ] El campo Cuenta Tercero se mapea al nuevo campo third_party_account
- [ ] Los centros de costos se validan contra el catálogo existente
- [ ] Se aplica el fallback de centros de costos cuando el campo está vacío
- [ ] El reemplazo atómico elimina registros existentes antes de insertar
- [ ] El endpoint DELETE elimina correctamente por document_number
- [ ] Se permiten datos duplicados en la tabla (no hay restricción de unicidad)

### 7.2 Criterios de Integridad
- [ ] Si un centro de costos no existe, se rechaza TODO el archivo (HTTP 400)
- [ ] Si hay error en cualquier fase, se ejecuta rollback completo
- [ ] Todas las operaciones son transaccionales (commit/rollback)
- [ ] El delete y insert del reemplazo atómico ocurren en la misma transacción

### 7.3 Criterios de Rendimiento
- [ ] Bulk insert sin límite de batch (todos los registros de una vez)
- [ ] Procesamiento de archivo de 10,000+ filas en menos de 30 segundos
- [ ] Respuesta del endpoint POST incluye conteo detallado de registros
- [ ] No se re-lee el archivo Excel después de la Fase A

### 7.4 Criterios de Seguridad
- [ ] Ambos endpoints requieren autenticación JWT
- [ ] Validación de tipos de archivo (solo .xlsx)
- [ ] Manejo adecuado de errores sin exponer información sensible

## 8. Dependencias y Consideraciones

### 8.1 Dependencias de Base de Datos
- Tabla cost_centers debe existir con códigos válidos
- Códigos de fallback (410100, 210700, 510100, 999100) deben estar presentes en cost_centers
- Se requiere ALTER TABLE para agregar columnas nuevas (accounting_account, document_number, third_party_account, updated_at)

### 8.2 Librerías Python Requeridas
- pandas >= 1.5.0 (ya en requirements.txt)
- openpyxl >= 3.0.0 (ya en requirements.txt)
- sqlalchemy >= 1.4.0 (ya en requirements.txt)
- fastapi >= 0.95.0 (ya en requirements.txt)
- python-multipart (ya en requirements.txt)

### 8.3 Archivos a Modificar (Checklist)

| # | Archivo | Acción | Registrado en __init__? |
|---|---------|--------|------------------------|
| 1 | `app/models/budget/actualExpense.py` | MODIFICAR (agregar 4 campos) | Ya registrado en `app/models/budget/__init__.py` |
| 2 | `app/schemas/budget/actualExpense.py` | MODIFICAR (agregar campos, quitar ge=0) | Ya registrado en `app/schemas/budget/__init__.py` |
| 3 | `app/crud/budget/actualExpense.py` | MODIFICAR (agregar 2 funciones) | Ya registrado en `app/crud/budget/__init__.py` |
| 4 | `app/api/budget/upload.py` | MODIFICAR (implementar stub líneas 38-49) | Ya registrado en `app/api/budget/__init__.py` |
| 5 | `app/api/budget/actualExpense.py` | MODIFICAR (agregar endpoint DELETE) | Ya registrado en `app/api/budget/__init__.py` |
| 6 | `app/utils/templates/budgetTemplates.py` | MODIFICAR (agregar 5 métodos ETL) | No aplica (métodos en clase existente) |

> **No se crean archivos nuevos.** Todos los archivos ya existen dentro del paquete `budget/`.

### 8.4 Orden de Implementación Sugerido

1. **Paso 1**: ALTER TABLE en base de datos (agregar columnas nuevas)
2. **Paso 2**: Actualizar modelo (`app/models/budget/actualExpense.py`)
3. **Paso 3**: Actualizar schemas (`app/schemas/budget/actualExpense.py`)
4. **Paso 4**: Agregar funciones CRUD (`app/crud/budget/actualExpense.py`)
5. **Paso 5**: Implementar métodos ETL en BudgetTemplates (`app/utils/templates/budgetTemplates.py`)
6. **Paso 6**: Implementar endpoint POST en upload.py (`app/api/budget/upload.py`)
7. **Paso 7**: Agregar endpoint DELETE en actualExpense.py (`app/api/budget/actualExpense.py`)
8. **Paso 8**: Prueba manual con archivo de ejemplo
