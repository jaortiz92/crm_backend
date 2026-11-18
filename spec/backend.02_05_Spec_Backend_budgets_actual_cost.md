# Especificacion Tecnica: ETL actual-costs (Costos Reales)

## 1. Objetivo del Proceso (Process Objective)

Establecer la tubería de ingesta de datos (ETL) para cargar el archivo CostosFinal.xlsx en la tabla actual_costs, garantizando trazabilidad de auditoría, vinculacion relacional con el catalogo de referencias, y mapeo correcto de centros de costo mediante inferencia de zona geografica desde facturas.

Adicionalmente, el sistema debe soportar:
- **Eliminacion masiva por document_number**: Permitir al usuario eliminar todos los registros asociados a un numero de documento en una sola operacion.
- **Reemplazo automatico de datos**: Si se carga un archivo con document_numbers que ya existen en la base de datos, el sistema debe eliminar los registros antiguos y reemplazarlos con los nuevos, todo dentro de una transaccion atomica.
- **Campo description**: Almacenar una descripcion opcional del costo. Para cargues masivos via ETL este campo se deja vacio; para cargues individuales via POST el usuario puede proporcionarlo.

---

## 2. Cambios en el Modelo de Datos (Schema Changes)

### 2.1 Modelo ActualCost - Campos

**Archivo:** crm_backend/app/models/budget/actualCost.py

```python
class ActualCost(Base):
    __tablename__ = "actual_costs"

    id_actual_cost = Column(Integer, primary_key=True, index=True)
    id_cost_center = Column(Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False)
    id_reference = Column(Integer, ForeignKey("product_references.id_reference"), nullable=True)
    document_number = Column(String(50), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, server_default="0")
    unit_cost = Column(Numeric(12, 2), nullable=False, server_default="0")
    cost_date = Column(Date, nullable=False)
    cost_type = Column(String(60), nullable=False)
    amount = Column(Float, nullable=False, server_default="0")
    description = Column(Text, nullable=True)  # NUEVO - vuelve, nullable
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    cost_center = relationship("CostCenter", back_populates="actual_costs")
    reference = relationship("Reference", back_populates="actual_costs")
```

### 2.2 Schema Pydantic - Actualizacion

**Archivo:** crm_backend/app/schemas/budget/actualCost.py

```python
class ActualCostBase(BaseModel):
    id_cost_center: int = Field(..., gt=0, description="FK to cost center")
    document_number: str = Field(..., max_length=50, description="Invoice/document number")
    id_reference: Optional[int] = Field(None, gt=0, description="FK to product reference")
    quantity: int = Field(..., ge=0, description="Quantity of units")
    unit_cost: float = Field(..., ge=0, description="Cost per unit")
    cost_date: date = Field(..., description="Date of the cost")
    cost_type: str = Field(..., max_length=60, description="Category of cost")
    amount: float = Field(..., ge=0, description="Total cost (quantity * unit_cost)")
    description: Optional[str] = Field(None, description="Optional description of the cost")
    source_file: Optional[str] = Field(None, max_length=200, description="Source Excel file")

class ActualCostCreate(ActualCostBase):
    pass

class ActualCost(ActualCostBase):
    id_actual_cost: int = Field(..., gt=0)
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True
```

### 2.3 Migracion de Base de Datos

**Accion requerida:** Agregar 4 columnas a la tabla actual_costs:
- document_number VARCHAR(50) NOT NULL
- quantity INTEGER NOT NULL DEFAULT 0
- unit_cost NUMERIC(12,2) NOT NULL DEFAULT 0
- description TEXT NULLABLE

**Nota:** Como el proyecto usa Base.metadata.create_all() (sin Alembic), se debe:
1. Eliminar la tabla existente (si hay datos, exportar primero)
2. O ejecutar ALTER TABLE manualmente
3. O recrear la base de datos completa

---

## 3. Flujo de Ejecucion del ETL (Execution Pipeline)

### Metodo Principal: process_cost() en BudgetTemplates

**Archivo:** crm_backend/app/utils/templates/budgetTemplates.py

El metodo debe seguir estas 5 fases estructurales:

---

### FASE A: Limpieza de Datos (Data Cleansing)

**Entrada:** Archivo Excel CostosFinal.xlsx (BytesIO)

**Proceso:**

```python
def process_cost(self) -> DataFrame:
    """
    Process CostosFinal.xlsx for actual cost records.

    Steps:
    1. Read Excel with header=3, skipfooter=1
    2. Rename columns to standard names
    3. Clean document numbers (FV->FVFE, PND->NDCL, etc.)
    4. Extract product code from description
    5. Cast numeric and date columns
    6. Calculate amount = quantity * unit_cost
    7. Set description to None (not persisted in bulk uploads)

    Returns:
        DataFrame with cleaned and transformed data
    """
    # 1. Leer Excel
    self.df = pd.read_excel(
        self.file,
        engine="openpyxl",
        header=3,
        skipfooter=1
    ).rename(columns={
        'Doc': 'document_number',
        'CodigoInventario': 'description',
        'Unidades': 'quantity',
        'Costo Unitario': 'unit_cost',
        'Fecha': 'cost_date'
    })

    # 2. Eliminar filas sin documento
    self.df.dropna(subset=['document_number'], inplace=True)

    # 3. Limpiar numeros de documento
    self.df['document_number'] = self.df['document_number'].apply(
        self._clean_document
    )

    # 4. Extraer codigo de producto de la descripcion
    self.df['reference_code'] = self.df['description'].apply(
        self._extract_reference_code
    )

    # 5. Castear tipos
    self.df['quantity'] = pd.to_numeric(self.df['quantity'], errors='coerce').fillna(0).astype(int)
    self.df['unit_cost'] = pd.to_numeric(self.df['unit_cost'], errors='coerce').fillna(0.0)
    self.df['cost_date'] = pd.to_datetime(self.df['cost_date'], errors='coerce').dt.date
    self.df['amount'] = self.df['quantity'] * self.df['unit_cost']

    # 6. Estandarizar texto
    self.df['document_number'] = self.df['document_number'].astype(str).str.strip()
    self.df['reference_code'] = self.df['reference_code'].astype(str).str.strip()

    # 7. Description se deja vacio para cargues masivos
    # (se usa solo para extraer reference_code, no se persiste)
    self.df['description'] = None

    return self.df
```

**Funciones auxiliares (extraidas de costs.py):**

```python
@staticmethod
def _clean_document(x: str) -> str:
    """
    Clean document number following business rules:
    - FV + not FE -> FVFE + suffix
    - DMCDMC -> remove prefix
    - PND -> NDCL + suffix
    - PNC -> NCCL + suffix
    - M- -> remove prefix
    """
    value = str(x).replace(' ', '')
    if 'FV' in value and 'FE' not in value:
        value = 'FVFE' + value[2:]
    elif 'DMCDMC' in value:
        value = value[3:]
    elif 'PND' in value:
        value = 'NDCL{}'.format(value[7:])
    elif 'PNC' in value:
        value = 'NCCL{}'.format(value[7:])
    elif 'M-' in value:
        value = value[2:]
    return value

@staticmethod
def _extract_reference_code(description: str) -> str:
    """
    Extract product code from description field.
    Takes first word before space.
    Example: "REF123 Zapatilla Nike" -> "REF123"
    """
    if not description or pd.isna(description):
        return ""
    return str(description).split(' ')[0].strip()
```

---

### FASE B: Mapeo Relacional (Data Mapping)

**Entrada:** DataFrame limpio de Fase A

**Proceso:**

```python
def _map_relational_data(self, db: Session) -> DataFrame:
    """
    Map Excel data to foreign keys:
    1. reference_code -> id_reference (from product_references)
    2. document_number -> id_zone (via invoice -> customer -> city -> department -> zone)
    3. id_zone + id_line + cost_center_code LIKE '00%' -> id_cost_center

    Returns:
        DataFrame with id_reference, id_cost_center added
    """
    # 1. Cargar mapeo de referencias en memoria
    references_map = {
        ref.reference: ref.id_reference
        for ref in db.query(ReferenceModel).all()
    }

    # 2. Cargar mapeo invoice_number -> id_zone en memoria
    invoice_zone_map = self._load_invoice_zone_mapping(db)

    # 3. Cargar mapeo (id_zone, id_line) -> id_cost_center
    cost_center_map = self._load_cost_center_mapping(db)

    # 4. Aplicar mapeos
    self.df['id_reference'] = self.df['reference_code'].map(references_map)

    # 5. Obtener id_zone desde document_number
    self.df['id_zone'] = self.df['document_number'].map(invoice_zone_map)

    # 6. Para cada fila, buscar Brand.id_line desde id_reference
    self.df['id_line'] = self.df['id_reference'].apply(
        lambda ref_id: self._get_line_from_reference(db, ref_id) if pd.notna(ref_id) else None
    )

    # 7. Buscar id_cost_center con filtros: id_zone + id_line + codigo inicia con "00"
    self.df['id_cost_center'] = self.df.apply(
        lambda row: self._find_cost_center(
            cost_center_map,
            row.get('id_zone'),
            row.get('id_line')
        ),
        axis=1
    )

    return self.df

def _load_invoice_zone_mapping(self, db: Session) -> Dict[str, int]:
    """
    Load invoice_number -> id_zone mapping into memory.

    Query path:
    invoice -> order -> customer_trip -> customer -> city -> department -> zone
    """
    query = db.query(
        InvoiceModel.invoice_number,
        DepartmentModel.id_zone
    ).join(
        OrderModel, OrderModel.id_order == InvoiceModel.id_order
    ).join(
        CustomerTripModel, CustomerTripModel.id_customer_trip == OrderModel.id_customer_trip
    ).join(
        CustomerModel, CustomerModel.id_customer == CustomerTripModel.id_customer
    ).join(
        CityModel, CityModel.id_city == CustomerModel.id_city
    ).join(
        DepartmentModel, DepartmentModel.id_department == CityModel.id_department
    )

    return {row.invoice_number: row.id_zone for row in query.all()}

def _load_cost_center_mapping(self, db: Session) -> Dict[Tuple[int, int], int]:
    """
    Load (id_zone, id_line) -> id_cost_center mapping.
    Only includes cost centers where code starts with '00'.
    """
    query = db.query(CostCenterModel).filter(
        CostCenterModel.cost_center_code.like('00%'),
        CostCenterModel.is_active == True
    )

    return {
        (cc.id_zone, cc.id_line): cc.id_cost_center
        for cc in query.all()
        if cc.id_zone is not None and cc.id_line is not None
    }

def _get_line_from_reference(self, db: Session, id_reference: int) -> Optional[int]:
    """Get id_line from reference via brand relationship."""
    ref = db.query(ReferenceModel).filter(
        ReferenceModel.id_reference == id_reference
    ).first()

    if ref and ref.id_brand:
        brand = db.query(BrandModel).filter(
            BrandModel.id_brand == ref.id_brand
        ).first()
        return brand.id_line if brand else None

    return None

def _find_cost_center(
    self,
    cost_center_map: Dict[Tuple[int, int], int],
    id_zone: Optional[int],
    id_line: Optional[int]
) -> Optional[int]:
    """Find cost center by (id_zone, id_line) combination."""
    if id_zone is None or id_line is None:
        return None
    return cost_center_map.get((id_zone, id_line))
```

---

### FASE C: Validaciones de Seguridad (Safety Checks)

**Entrada:** DataFrame con mapeos aplicados

**Proceso:**

```python
def _validate_data_integrity(self, db: Session, excel_total_cost: float) -> None:
    """
    Validate data integrity before insertion:
    1. Check all references exist in catalog
    2. Check all cost centers were resolved
    3. Validate SUM(amount) matches Excel Total Cost (tolerance: 100)
    """
    # 1. Validar referencias faltantes
    missing_references = self.df[
        self.df['id_reference'].isna() &
        self.df['reference_code'].notna() &
        (self.df['reference_code'] != "")
    ]['reference_code'].unique().tolist()

    if missing_references:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"References not found in catalog: {missing_references}"
        )

    # 2. Validar centros de costo faltantes
    missing_cost_centers = self.df[self.df['id_cost_center'].isna()]

    if not missing_cost_centers.empty:
        error_details = []
        for _, row in missing_cost_centers.head(10).iterrows():
            error_details.append({
                "document_number": row['document_number'],
                "reference_code": row['reference_code'],
                "id_zone": row.get('id_zone'),
                "id_line": row.get('id_line'),
                "reason": "Cost center not found with filters: id_zone + id_line + code LIKE '00%'"
            })

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"Could not resolve cost center for {len(missing_cost_centers)} records",
                "examples": error_details[:10]
            }
        )

    # 3. Validar suma total con tolerancia de 100
    calculated_total = self.df['amount'].sum()

    if abs(calculated_total - excel_total_cost) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Total amount validation failed",
                "excel_total": excel_total_cost,
                "calculated_total": calculated_total,
                "difference": abs(calculated_total - excel_total_cost),
                "tolerance": 100
            }
        )
```

---

### FASE D: Deteccion de Duplicados y Reemplazo (NEW)

**Entrada:** DataFrame validado de Fase C

**Proceso:**

```python
def _handle_duplicate_documents(self, db: Session) -> int:
    """
    Detect if any document_number in the new file already exists in DB.
    If duplicates found, delete all existing records with those document_numbers.

    Returns:
        Number of records deleted (0 if no duplicates)
    """
    # 1. Obtener document_numbers unicos del nuevo archivo
    new_document_numbers = self.df['document_number'].unique().tolist()

    # 2. Verificar si alguno ya existe en la base de datos
    existing_records = db.query(ActualCostModel).filter(
        ActualCostModel.document_number.in_(new_document_numbers)
    ).all()

    if not existing_records:
        return 0  # No hay duplicados, no se elimina nada

    # 3. Eliminar todos los registros con esos document_numbers
    deleted_count = db.query(ActualCostModel).filter(
        ActualCostModel.document_number.in_(new_document_numbers)
    ).delete(synchronize_session=False)

    return deleted_count
```

**Nota importante:** Esta eliminacion se ejecuta DENTRO de la misma transaccion que el bulk insert posterior. Si el bulk insert falla, se hace rollback y los registros eliminados se restauran.

---

### FASE E: Insercion Masiva (Bulk Insert)

**Entrada:** DataFrame validado y sin duplicados en DB

**Proceso:**

```python
def _bulk_insert(self, db: Session, source_filename: str) -> List[ActualCostModel]:
    """
    Convert DataFrame to records and perform bulk insert.
    Transaction is atomic (all-or-nothing).
    Description field is set to None for bulk uploads.
    """
    records = []
    for _, row in self.df.iterrows():
        records.append(ActualCostCreate(
            id_cost_center=row['id_cost_center'],
            document_number=row['document_number'],
            id_reference=int(row['id_reference']) if pd.notna(row['id_reference']) else None,
            quantity=int(row['quantity']),
            unit_cost=float(row['unit_cost']),
            cost_date=row['cost_date'],
            cost_type='invoice',
            amount=float(row['amount']),
            description=None,  # VACIO para cargues masivos
            source_file=source_filename,
        ))

    return crud.create_actual_costs_bulk(db, records)
```

---

## 4. Endpoints API

### 4.1 Upload Endpoint (con reemplazo automatico)

**Archivo:** crm_backend/app/api/budget/upload.py

```python
@router.post("/actual-costs")
async def upload_actual_costs(
    file: UploadFile = File(...),
    excel_total_cost: float = Form(..., description="Total cost from Excel for validation"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and process CostosFinal.xlsx for actual costs.

    Process:
    1. Read Excel file
    2. Clean and transform data (document numbers, reference codes)
    3. Map references to id_reference
    4. Infer id_zone from invoice -> customer -> city -> department
    5. Resolve id_cost_center using (id_zone, id_line, code LIKE '00%')
    6. Validate data integrity (missing references, cost centers, total amount)
    7. NEW: Detect duplicates and delete existing records with same document_numbers
    8. Bulk insert into actual_costs table

    Returns:
        JSON with insertion summary, including replacement info if applicable
    """
    file_content = await file.read()
    file_bytes = BytesIO(file_content)

    try:
        # Fase A: Limpieza
        etl = BudgetTemplates(file_bytes)
        df = etl.process_cost()

        # Fase B: Mapeo relacional
        df = etl._map_relational_data(db)

        # Fase C: Validaciones
        etl._validate_data_integrity(db, excel_total_cost)

        # Fase D: Deteccion de duplicados y reemplazo
        records_deleted = etl._handle_duplicate_documents(db)

        # Fase E: Insercion masiva
        inserted_records = etl._bulk_insert(db, file.filename)

        response = {
            "message": "Actual costs uploaded successfully",
            "records_inserted": len(inserted_records),
            "total_amount": sum(r.amount for r in inserted_records),
            "source_file": file.filename,
            "replaced": records_deleted > 0,
            "records_deleted": records_deleted
        }

        return response

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing actual costs: {str(e)}"
        )
```

**Respuesta cuando hay reemplazo:**

```json
{
    "message": "Actual costs uploaded successfully",
    "records_inserted": 150,
    "total_amount": 125000.00,
    "source_file": "CostosFinal.xlsx",
    "replaced": true,
    "records_deleted": 120
}
```

**Respuesta cuando NO hay reemplazo (carga fresca):**

```json
{
    "message": "Actual costs uploaded successfully",
    "records_inserted": 150,
    "total_amount": 125000.00,
    "source_file": "CostosFinal.xlsx",
    "replaced": false,
    "records_deleted": 0
}
```

---

### 4.2 Delete Endpoint por Document Number (NUEVO)

**Archivo:** crm_backend/app/api/budget/actualCost.py

```python
@router.delete("/by-document/{document_number}")
def delete_actual_costs_by_document(
    document_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all actual cost records associated with a specific document_number.

    This allows bulk deletion of all costs related to a single invoice/document.

    Returns:
        JSON with count of deleted records
    """
    deleted_count = crud.delete_actual_costs_by_document(db, document_number)

    if deleted_count == 0:
        Exceptions.register_not_found("ActualCost", f"document_number={document_number}")

    return {
        "message": f"Actual costs deleted successfully for document_number: {document_number}",
        "records_deleted": deleted_count
    }
```

**CRUD function (agregar a crm_backend/app/crud/budget/actualCost.py):**

```python
def delete_actual_costs_by_document(db: Session, document_number: str) -> int:
    """
    Delete all actual cost records with the given document_number.
    Returns the number of records deleted.
    """
    deleted_count = db.query(ActualCostModel).filter(
        ActualCostModel.document_number == document_number
    ).delete(synchronize_session=False)
    db.commit()
    return deleted_count
```

---

### 4.3 POST Individual (con description opcional)

**Archivo:** crm_backend/app/api/budget/actualCost.py

El endpoint POST existente para crear un solo registro ahora acepta el campo `description` como opcional:

```python
@router.post("/")
def create_actual_cost(
    actual_cost: ActualCostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a single actual cost record.
    The 'description' field is optional and can be provided by the user.
    """
    return crud.create_actual_cost(db, actual_cost)
```

**Ejemplo de request body:**

```json
{
    "id_cost_center": 5,
    "document_number": "FVFE001234",
    "id_reference": 42,
    "quantity": 10,
    "unit_cost": 50.00,
    "cost_date": "2024-01-15",
    "cost_type": "invoice",
    "amount": 500.00,
    "description": "Costo de transporte para cliente ABC",
    "source_file": null
}
```

---

## 5. Criterios de Aceptacion (Acceptance Criteria)

### 5.1 Criterios Funcionales

- [ ] El archivo CostosFinal.xlsx se carga correctamente con header=3, skipfooter=1
- [ ] Los numeros de documento se limpian segun reglas: FV->FVFE, PND->NDCL, PNC->NCCL, DMCDMC->, M-->
- [ ] El codigo de referencia se extrae correctamente de la descripcion (primera palabra antes de espacio)
- [ ] La busqueda de id_reference en product_references.reference funciona correctamente
- [ ] El mapeo invoice_number -> id_zone se carga en memoria al inicio del ETL
- [ ] El mapeo id_zone + id_line -> id_cost_center solo incluye codigos que inician con "00"
- [ ] Los campos quantity (integer) y unit_cost (numeric) se almacenan correctamente
- [ ] El campo amount se calcula como quantity * unit_cost
- [ ] El campo cost_type se establece como 'invoice' para todos los registros
- [ ] La validacion SUM(amount) = Total_Costo permite tolerancia de 100 unidades monetarias
- [ ] El campo description existe en el modelo y es nullable (TEXT)
- [ ] Para cargues masivos (ETL), el campo description se almacena como NULL
- [ ] Para cargues individuales (POST), el campo description puede ser proporcionado por el usuario

### 5.2 Criterios de Eliminacion Masiva por Document Number

- [ ] El endpoint DELETE /budget/actual-cost/by-document/{document_number} existe y funciona
- [ ] El endpoint elimina TODOS los registros con ese document_number en una sola operacion
- [ ] El endpoint retorna la cantidad de registros eliminados
- [ ] Si no existen registros con ese document_number, se retorna HTTP 404
- [ ] El endpoint requiere autenticacion (get_current_user)
- [ ] La eliminacion es atomica (se hace commit solo si la operacion completa es exitosa)

### 5.3 Criterios de Reemplazo Automatico

- [ ] Al cargar un archivo, el sistema detecta si alguno de los document_numbers ya existe en la DB
- [ ] Si hay document_numbers duplicados, se eliminan TODOS los registros existentes con esos document_numbers antes de insertar los nuevos
- [ ] La eliminacion de registros antiguos y la insercion de nuevos ocurren en la MISMA transaccion atomica
- [ ] Si el bulk insert falla despues de eliminar registros, se hace rollback y los registros eliminados se restauran
- [ ] La respuesta del endpoint indica si se hizo un reemplazo (campo "replaced": true/false)
- [ ] La respuesta incluye la cantidad de registros eliminados (campo "records_deleted")
- [ ] Si no hay duplicados, la carga funciona normalmente sin eliminar nada

### 5.4 Criterios de Validacion

- [ ] Si existen referencias no encontradas en el catalogo, se retorna HTTP 400 con lista detallada
- [ ] Si no se puede resolver id_cost_center para algun registro, se retorna HTTP 400 con ejemplos
- [ ] Si la diferencia de totales supera 100, se retorna HTTP 400 con detalles de la discrepancia
- [ ] La transaccion es atomica: si falla cualquier validacion, se hace rollback completo

### 5.5 Criterios de Rendimiento

- [ ] El mapeo en memoria (invoice->zone, cost_centers) se carga una sola vez al inicio
- [ ] El bulk insert se ejecuta en una unica transaccion SQLAlchemy
- [ ] El proceso completo para 10,000 registros debe completarse en < 30 segundos
- [ ] La deteccion de duplicados usa un query eficiente con IN clause (no iteracion fila por fila)

### 5.6 Criterios de Trazabilidad

- [ ] El campo source_file almacena el nombre del archivo Excel procesado
- [ ] El campo document_number permite rastrear el origen de cada costo
- [ ] El campo created_at registra automaticamente la fecha/hora de insercion
- [ ] El campo description permite agregar contexto adicional en cargues individuales

---

## 6. Registro de Cambios (Change Log)

### Archivos a Modificar:

1. **crm_backend/app/models/budget/actualCost.py**
   - Agregar campo: description (Text, nullable)

2. **crm_backend/app/schemas/budget/actualCost.py**
   - Agregar campo description: Optional[str] a ActualCostBase

3. **crm_backend/app/crud/budget/actualCost.py**
   - Agregar funcion: delete_actual_costs_by_document(db, document_number)

4. **crm_backend/app/api/budget/actualCost.py**
   - Agregar endpoint: DELETE /by-document/{document_number}

5. **crm_backend/app/utils/templates/budgetTemplates.py**
   - Agregar metodo: _handle_duplicate_documents(db) (FASE D)
   - Actualizar _bulk_insert() para establecer description=None
   - Actualizar process_cost() para establecer description=None despues de extraer reference_code

6. **crm_backend/app/api/budget/upload.py**
   - Actualizar endpoint POST /actual-costs para incluir Fase D (deteccion de duplicados)
   - Actualizar respuesta para incluir campos "replaced" y "records_deleted"

7. **Base de datos**
   - Agregar columna description TEXT NULLABLE a tabla actual_costs

---

## 7. Notas Tecnicas (Technical Notes)

### 7.1 Optimizacion de Consultas

Se utiliza **carga en memoria** para los mapeos relacionales:
- invoice_number -> id_zone: ~5 JOINs evitados por fila
- (id_zone, id_line) -> id_cost_center: filtro pre-cargado

Esto reduce el tiempo de procesamiento de O(n * 5 JOINs) a O(n) lookups en diccionario.

### 7.2 Manejo de Errores

Todos los errores de validacion retornan HTTP 400 con estructura detallada:

```json
{
  "detail": {
    "message": "Error description",
    "missing_items": [...],
    "examples": [...]
  }
}
```

### 7.3 Transaccionalidad

El bulk insert y la eliminacion de duplicados son **atomicos** (all-or-nothing):
- Si cualquier validacion falla -> rollback completo
- Si la eliminacion de duplicados falla -> rollback completo
- Si el bulk insert falla despues de eliminar duplicados -> rollback completo (los registros eliminados se restauran)
- Solo se hace commit si todo el proceso es exitoso

### 7.4 Campo Description - Comportamiento Dual

El campo `description` tiene dos comportamientos segun el tipo de carga:

| Tipo de Carga | Campo description | Razon |
|---------------|-------------------|-------|
| Masiva (ETL/Excel) | NULL / vacio | La descripcion del Excel se usa solo para extraer reference_code, no se persiste |
| Individual (POST) | Opcional, proporcionada por usuario | Permite agregar contexto especifico a un costo puntual |

### 7.5 Estrategia de Reemplazo

El reemplazo automatico funciona asi:

1. Se extraen los document_numbers unicos del nuevo archivo
2. Se consulta si alguno ya existe en la DB
3. Si existen, se eliminan TODOS los registros con esos document_numbers
4. Se insertan los nuevos registros
5. Todo dentro de la misma transaccion

**Ventaja:** El usuario no necesita eliminar manualmente antes de re-cargar.
**Garantia:** La transaccionalidad asegura que nunca se pierdan datos (si falla el insert, los datos antiguos se restauran).

---

**Fin de la Especificacion Tecnica**
