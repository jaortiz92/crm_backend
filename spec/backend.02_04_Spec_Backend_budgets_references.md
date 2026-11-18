# Especificación: Product References Table

## 1. Resumen Ejecutivo

Se creará una tabla maestra llamada `product_references` que centralizará toda la información de referencias del sistema. Esta tabla permitirá operaciones CRUD individuales y operaciones masivas (creación/actualización/eliminación) mediante archivos Excel.

---

## 2. Estructura de la Base de Datos

### 2.1 Tabla `product_references`

| Campo | Tipo | Nullable | Constraints | Descripción |
|-------|------|----------|-------------|-------------|
| `id_reference` | Integer | No | PK, Auto-increment | Identificador único |
| `reference` | String(100) | No | UNIQUE, INDEX | Código de referencia |
| `id_brand` | Integer | No | FK → `brands.id_brand` | Marca asociada |
| `description` | String(500) | Sí | - | Descripción de la referencia |
| `gender` | Enum(Gender) | No | - | Género (U=0, M=1, F=2) |
| `value_base` | Numeric(12,2) | No | - | Valor base monetario |
| `id_collection` | Integer | Sí | FK → `collections.id_collection` | Colección asociada (opcional) |
| `created_at` | DateTime | No | server_default=now() | Timestamp de creación |
| `updated_at` | DateTime | No | server_default=now(), onupdate=now() | Timestamp de actualización |

**Relaciones:**
- `brand` → Relationship con tabla `brands`
- `collection` → Relationship con tabla `collections`

### 2.2 Modificaciones en Tablas Existentes

#### Tabla `actual_costs`
- **Agregar campo**: `id_reference` (Integer, FK → `product_references.id_reference`, nullable=True)
- **Agregar relationship**: `reference` → Relationship con `product_references`

#### Tabla `order_details`
- **Agregar campo**: `id_reference` (Integer, FK → `product_references.id_reference`, nullable=True)
- **Agregar relationship**: `reference` → Relationship con `product_references`

#### Tabla `invoice_details`
- **Agregar campo**: `id_reference` (Integer, FK → `product_references.id_reference`, nullable=True)
- **Agregar relationship**: `reference` → Relationship con `product_references`

---

## 3. Endpoints del Backend

### 3.1 Endpoints CRUD Individual

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/references` | Listar todas las referencias (con paginación) |
| GET | `/references/{id_reference}` | Obtener referencia por ID |
| POST | `/references` | Crear nueva referencia |
| PUT | `/references/{id_reference}` | Actualizar referencia existente |
| DELETE | `/references/{id_reference}` | Eliminar referencia individual |

### 3.2 Endpoints de Operaciones Masivas

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/references/upload` | Crear/actualizar referencias desde Excel |
| POST | `/references/delete-bulk` | Eliminar múltiples referencias desde Excel |
| GET | `/references/template` | Descargar plantilla Excel para carga |
| GET | `/references/template-delete` | Descargar plantilla Excel para eliminación |

---

## 4. Especificación de Operaciones Masivas

### 4.1 Carga Masiva (Upload)

**Archivo de entrada:** Excel `.xlsx`

**Columnas del Excel (en español):**
| Columna | Obligatorio | Descripción |
|---------|-------------|-------------|
| `Referencia` | Sí | Código de referencia (campo `reference`) |
| `Marca` | Sí | Nombre de marca (campo `brand_name`) |
| `Descripción` | No | Descripción de la referencia |
| `Género` | Sí | Valor del enum: 'U', 'M', o 'F' |
| `Valor Base` | Sí | Valor numérico (formato decimal con punto o coma) |
| `Colección` | No | Nombre corto de colección (campo `short_collection_name`) |

**Comportamiento:**
1. **Upsert**: Si la `reference` ya existe → actualizar; si no existe → insertar nueva
2. **Validaciones:**
   - `Referencia` y `Marca` son obligatorios en cada fila
   - `Marca` debe existir en tabla `brands` (búsqueda por `brand_name`)
   - `Colección` (si se proporciona) debe existir en tabla `collections` (búsqueda por `short_collection_name`)
   - `Género` debe ser uno de: 'U', 'M', 'F'
   - `Valor Base` debe ser numérico
3. **Transaccional**: Si alguna fila falla, se rechaza todo el archivo (rollback)
4. **Respuesta exitosa:**
```json
{
  "message": "Carga masiva completada",
  "total_filas": 150,
  "insertadas": 30,
  "actualizadas": 120,
  "errores": []
}
```

### 4.2 Eliminación Masiva (Delete Bulk)

**Archivo de entrada:** Excel `.xlsx`

**Columnas del Excel:**
| Columna | Obligatorio | Descripción |
|---------|-------------|-------------|
| `Referencia` | Sí | Código de referencia a eliminar |

**Comportamiento:**
1. **Validación de uso**: Antes de eliminar, verificar que ninguna referencia esté siendo usada en `actual_costs` (campo `id_reference`)
2. **Validación de existencia**: Verificar que todas las referencias del Excel existan en `product_references`
3. **Transaccional estricto**: 
   - Si **TODAS** las referencias pasan la validación → eliminar todas
   - Si **al menos una** referencia está en uso o no existe → rechazar todo el archivo, no eliminar nada
4. **Respuesta exitosa:**
```json
{
  "message": "Eliminación masiva completada",
  "total_eliminadas": 25,
  "referencias_eliminadas": ["REF001", "REF002", "..."]
}
```
5. **Respuesta de error (si alguna está en uso):**
```json
{
  "message": "No se puede eliminar: las siguientes referencias están en uso",
  "referencias_en_uso": ["REF003", "REF007"],
  "tabla_afectada": "actual_costs"
}
```

### 4.3 Plantillas Excel

**Plantilla de carga (`/template`):**
- Archivo Excel con las columnas en español
- Primera fila con encabezados
- Segunda fila con datos de ejemplo
- Nombre del archivo: `plantilla_referencias.xlsx`

**Plantilla de eliminación (`/template-delete`):**
- Archivo Excel con una sola columna: `Referencia`
- Primera fila con encabezado
- Segunda fila con dato de ejemplo
- Nombre del archivo: `plantilla_eliminar_referencias.xlsx`

---

## 5. Modelos de Datos (Pydantic Schemas)

### 5.1 Reference (Response)
```python
class Reference(BaseModel):
    id_reference: int
    reference: str
    id_brand: int
    description: Optional[str]
    gender: Gender
    value_base: float
    id_collection: Optional[int]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
```

### 5.2 ReferenceCreate (Input)
```python
class ReferenceCreate(BaseModel):
    reference: str = Field(..., min_length=1, max_length=100)
    id_brand: int = Field(..., gt=0)
    description: Optional[str] = Field(None, max_length=500)
    gender: Gender
    value_base: float = Field(..., ge=0)
    id_collection: Optional[int] = Field(None, gt=0)
```

### 5.3 BulkUploadResult (Response)
```python
class BulkUploadResult(BaseModel):
    message: str
    total_filas: int
    insertadas: int
    actualizadas: int
    errores: List[str]
```

### 5.4 BulkDeleteResult (Response)
```python
class BulkDeleteResult(BaseModel):
    message: str
    total_eliminadas: int
    referencias_eliminadas: List[str]
```

---

## 6. Estructura de Archivos (Backend)

### 6.1 Nuevos Archivos a Crear

```
crm_backend/app/
├── models/
│   └── reference.py                # Nuevo modelo
├── schemas/
│   └── reference.py                # Nuevos schemas
├── crud/
│   └── reference.py                # Nuevas operaciones CRUD
└── api/
    └── reference.py                # Nuevos endpoints
```

### 6.2 Archivos a Modificar

```
crm_backend/app/
├── models/
│   ├── __init__.py                 # Registrar Reference
│   └── budget/
│       └── actualCost.py           # Agregar id_reference field
├── schemas/
│   └── __init__.py                 # Registrar schemas
├── crud/
│   └── __init__.py                 # Registrar CRUD
├── api/
│   ├── __init__.py                 # Registrar router
│   └── budget/
│       └── actualCost.py           # Actualizar schema si es necesario
└── main.py                         # Incluir router
```

---

## 7. Reglas de Negocio

### 7.1 Validaciones de Integridad
1. **Unicidad de referencia**: No pueden existir dos registros con el mismo código `reference`
2. **Existencia de marca**: `id_brand` debe referenciar una marca existente
3. **Existencia de colección**: Si se proporciona `id_collection`, debe referenciar una colección existente
4. **Género válido**: Solo se aceptan valores del enum Gender (U, M, F)
5. **Valor base no negativo**: `value_base` debe ser ≥ 0

### 7.2 Reglas de Eliminación
1. **Protección de referencias en uso**: No se puede eliminar una referencia si está siendo usada en `actual_costs`
2. **Eliminación atómica**: En eliminación masiva, si una referencia falla, ninguna se elimina
3. **Hard delete**: Las eliminaciones son físicas (no soft delete)

### 7.3 Reglas de Carga Masiva
1. **Transaccional**: Todo o nada - si una fila falla, se rechaza todo el archivo
2. **Upsert automático**: Referencias existentes se actualizan, nuevas se insertan
3. **Búsqueda por nombre**: Marcas y colecciones se buscan por sus nombres (no IDs) en el Excel

---

## 8. Criterios de Aceptación

### 8.1 Base de Datos
- [ ] Tabla `product_references` creada con todos los campos especificados
- [ ] Campo `id_reference` agregado a `actual_costs`, `order_details`, `invoice_details` (nullable)
- [ ] Foreign keys correctamente configuradas
- [ ] Índices creados en `reference`, `id_brand`, `id_collection`

### 8.2 Endpoints CRUD
- [ ] GET `/references` retorna lista paginada
- [ ] GET `/references/{id}` retorna referencia específica
- [ ] POST `/references` crea nueva referencia con validaciones
- [ ] PUT `/references/{id}` actualiza referencia existente
- [ ] DELETE `/references/{id}` elimina referencia (con validación de uso)

### 8.3 Operaciones Masivas
- [ ] POST `/references/upload` procesa Excel correctamente
- [ ] Upsert funciona: inserta nuevas, actualiza existentes
- [ ] Validación de marcas y colecciones por nombre
- [ ] Transaccional: rollback si alguna fila falla
- [ ] POST `/references/delete-bulk` elimina múltiples referencias
- [ ] Validación de uso en `actual_costs` antes de eliminar
- [ ] Eliminación atómica: si una falla, ninguna se elimina
- [ ] GET `/references/template` descarga plantilla de carga
- [ ] GET `/references/template-delete` descarga plantilla de eliminación

### 8.4 Seguridad
- [ ] Todos los endpoints requieren autenticación JWT
- [ ] Solo usuarios autenticados pueden realizar operaciones

---

## 9. Notas Técnicas

### 9.1 Patrones a Seguir
- **Modelo**: Seguir patrón de `Brand` y `Collection` (FKs, relationships)
- **CRUD**: Usar patrón legacy `db.query(Model).filter(...)`
- **Schemas**: Usar Pydantic v2 con `from_attributes = True`
- **API**: Seguir estructura de endpoints existentes (get, create, update, delete)
- **Excel processing**: Usar `openpyxl` como en otros módulos de carga masiva

### 9.2 Consideraciones Futuras
- La validación de eliminación en `order_details` e `invoice_details` se implementará después
- Los campos `id_reference` en esas tablas ya estarán listos para la validación futura
- Se recomienda migrar gradualmente los valores de `product` a `id_reference` en esas tablas

---

## 10. Ejemplos de Uso

### 10.1 Carga Masiva Exitosa
```
POST /references/upload
Content-Type: multipart/form-data
Authorization: Bearer <token>

File: referencias.xlsx

Response 200:
{
  "message": "Carga masiva completada",
  "total_filas": 100,
  "insertadas": 25,
  "actualizadas": 75,
  "errores": []
}
```

### 10.2 Eliminación Masiva Exitosa
```
POST /references/delete-bulk
Content-Type: multipart/form-data
Authorization: Bearer <token>

File: eliminar.xlsx

Response 200:
{
  "message": "Eliminación masiva completada",
  "total_eliminadas": 10,
  "referencias_eliminadas": ["REF001", "REF002", "..."]
}
```

### 10.3 Eliminación Masiva con Error
```
POST /references/delete-bulk
File: eliminar.xlsx

Response 400:
{
  "message": "No se puede eliminar: las siguientes referencias están en uso",
  "referencias_en_uso": ["REF003"],
  "tabla_afectada": "actual_costs"
}
```

---

