# Especificación Backend: Mejora en Gestión de Actividades Obligatorias

> Spec derivado de `spec/00_Update_ActivityTypeManager.md` — Capa: Backend (`crm_backend/`)

## Contexto

El backend actual no valida la integridad del orden de actividades obligatorias. Depende 100% del frontend para mantener la secuencia consecutiva. Esto causa inconsistencias cuando:
- Se eliminan actividades (quedan gaps en el orden)
- Se reordenan manualmente (el frontend puede enviar datos inválidos)
- Se crean actividades (no se asigna automáticamente el siguiente orden disponible)

### Estado actual del código

| Archivo | Estado actual |
|---------|---------------|
| `app/schemas/activityType.py` | Schema básico sin validación de orden |
| `app/crud/activityType.py` | CRUD estándar (create, read, update, delete) |
| `app/api/activityType.py` | Endpoints CRUD sin lógica de reordenamiento |

### Modelo de datos (`activity_types`)

```python
class ActivityType(Base):
    __tablename__ = "activity_types"
    id_activity_type = Column(Integer, primary_key=True, index=True)
    activity = Column(String(100), unique=True, index=True, nullable=False)
    mandatory = Column(Boolean, nullable=False)
    category = Column(String(30), unique=True, index=True, nullable=False)
    activity_order = Column(Integer, nullable=False)
```

---

## Cambios Requeridos

### 1. Schema Pydantic (`app/schemas/activityType.py`)

#### 1.1. Actualizar `ActivityTypeBase` con validación

**Cambio:** Agregar validación personalizada para `activity_order` según `mandatory`.

```python
from pydantic import BaseModel, Field, validator

class ActivityTypeBase(BaseModel):
    activity: str = Field(
        ...,
        max_length=100,
        description='Activity name (max 100 characters)'
    )
    mandatory: bool = Field(
        ...,
        description='Whether the activity is mandatory'
    )
    category: str = Field(
        ...,
        max_length=30,
        description='Category name (max 30 characters)'
    )
    activity_order: int = Field(
        0,
        description='Order of the activity (0 for non-mandatory)'
    )

    @validator('activity_order')
    def validate_activity_order(cls, v, values):
        mandatory = values.get('mandatory')
        if mandatory and v < 1:
            raise ValueError('Mandatory activities must have activity_order >= 1')
        if not mandatory and v != 0:
            raise ValueError('Non-mandatory activities must have activity_order = 0')
        return v
```

**Reglas de validación:**
| Condición | `activity_order` permitido |
|-----------|---------------------------|
| `mandatory = TRUE` | `>= 1` |
| `mandatory = FALSE` | `= 0` |

#### 1.2. Crear schemas para batch reorder

**Nuevos schemas:**

```python
class ActivityTypeReorder(BaseModel):
    id_activity_type: int = Field(..., gt=0)
    activity_order: int = Field(..., gt=0)

class ActivityTypeBatchReorder(BaseModel):
    activities: list[ActivityTypeReorder] = Field(..., min_length=1)
```

#### 1.3. Registro en `app/schemas/__init__.py`

**Línea actual (2):**
```python
from .activityType import ActivityType, ActivityTypeCreate
```

**Línea nueva:**
```python
from .activityType import ActivityType, ActivityTypeCreate, ActivityTypeBatchReorder
```

---

### 2. CRUD (`app/crud/activityType.py`)

#### 2.1. Nueva función: `batch_reorder_mandatory_activities`

**Propósito:** Actualizar el orden de múltiples actividades obligatorias en una sola transacción atómica.

```python
def batch_reorder_mandatory_activities(
    db: Session, 
    reorder_data: list[dict]
) -> list[ActivityTypeSchema]:
    """Reordenar múltiples actividades obligatorias de forma atómica."""
    try:
        updated_activities = []
        for item in reorder_data:
            db_activity = db.query(ActivityTypeModel).filter(
                ActivityTypeModel.id_activity_type == item['id_activity_type']
            ).first()
            
            if db_activity and db_activity.mandatory:
                db_activity.activity_order = item['activity_order']
                updated_activities.append(db_activity)
        
        db.commit()
        for activity in updated_activities:
            db.refresh(activity)
        return updated_activities
    except Exception as e:
        db.rollback()
        raise e
```

**Comportamiento:**
- Solo actualiza actividades que sean `mandatory = TRUE`
- Si una actividad no es obligatoria, la ignora silenciosamente
- Transacción atómica: si falla, hace rollback

#### 2.2. Nueva función: `renumber_mandatory_activities_after_delete`

**Propósito:** Después de eliminar una actividad obligatoria, decrementar el orden de todas las actividades con orden mayor.

```python
def renumber_mandatory_activities_after_delete(
    db: Session, 
    deleted_order: int
) -> list[ActivityTypeSchema]:
    """Renumerar actividades obligatorias después de eliminar una."""
    try:
        activities_to_renumber = db.query(ActivityTypeModel).filter(
            ActivityTypeModel.mandatory == True,
            ActivityTypeModel.activity_order > deleted_order
        ).order_by(ActivityTypeModel.activity_order.asc()).all()
        
        for activity in activities_to_renumber:
            activity.activity_order -= 1
        
        db.commit()
        for activity in activities_to_renumber:
            db.refresh(activity)
        return activities_to_renumber
    except Exception as e:
        db.rollback()
        raise e
```

**Ejemplo:**
```
Antes de eliminar (orden 3):
  ID=1, order=1
  ID=2, order=2
  ID=3, order=3  <-- eliminar
  ID=4, order=4
  ID=5, order=5

Después de renumerar:
  ID=1, order=1
  ID=2, order=2
  ID=4, order=3  <-- decrementado
  ID=5, order=4  <-- decrementado
```

---

### 3. Endpoints API (`app/api/activityType.py`)

#### 3.1. Nuevo endpoint: `PUT /activity_type/reorder/`

**Propósito:** Recibir una lista de actividades con sus nuevos órdenes y actualizarlas atómicamente.

```python
from fastapi import HTTPException, status

@activity_type.put("/reorder/", response_model=List[ActivityType])
def batch_reorder_activity_types(
    reorder_data: ActivityTypeBatchReorder,
    db: Session = Depends(get_db)
):
    """
    Reordenar actividades obligatorias
    
    Recibe una lista de actividades con sus nuevos órdenes y las actualiza
    de forma atómica. Valida que no haya órdenes duplicados y que todas
    las actividades sean obligatorias.
    """
    # Validar órdenes duplicados
    orders = [item.activity_order for item in reorder_data.activities]
    if len(orders) != len(set(orders)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate activity_order values are not allowed"
        )
    
    # Validar que todas las actividades existan y sean obligatorias
    for item in reorder_data.activities:
        activity = crud.get_activity_type_by_id(db, item.id_activity_type)
        if not activity:
            Exceptions.register_not_found("Activity type", item.id_activity_type)
        if not activity.mandatory:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Activity type {item.id_activity_type} is not mandatory"
            )
    
    # Ejecutar reordenamiento
    result = crud.batch_reorder_mandatory_activities(
        db, 
        [item.model_dump() for item in reorder_data.activities]
    )
    return result
```

**Validaciones:**
1. No permitir órdenes duplicados en el request
2. Verificar que cada actividad exista
3. Verificar que cada actividad sea obligatoria (`mandatory = TRUE`)

**Request body ejemplo:**
```json
{
  "activities": [
    {"id_activity_type": 1, "activity_order": 3},
    {"id_activity_type": 2, "activity_order": 1},
    {"id_activity_type": 3, "activity_order": 2}
  ]
}
```

**Response ejemplo:**
```json
[
  {"id_activity_type": 1, "activity": "Invitación a Lanzamiento", "mandatory": true, "category": "pre", "activity_order": 3},
  {"id_activity_type": 2, "activity": "Lanzamiento de Colección", "mandatory": true, "category": "pre", "activity_order": 1},
  {"id_activity_type": 3, "activity": "Evaluación de Lanzamiento", "mandatory": true, "category": "pre", "activity_order": 2}
]
```

#### 3.2. Modificar endpoint: `DELETE /activity_type/{id_activity_type}`

**Cambio:** Después de eliminar, renumerar las actividades restantes si la eliminada era obligatoria.

**Código actual (líneas 124-146):**
```python
@activity_type.delete("/{id_activity_type}")
def delete_activity_type(id_activity_type: int, db: Session = Depends(get_db)):
    success = crud.delete_activity_type(db, id_activity_type)
    if not success['deleted']:
        if success['elimination_allow']:
            Exceptions.register_not_found("Activity type", id_activity_type)
        else:
            Exceptions.conflict_with_register("Activity type", id_activity_type)
    return {"message": "Activity type deleted successfully"}
```

**Código nuevo:**
```python
@activity_type.delete("/{id_activity_type}")
def delete_activity_type(id_activity_type: int, db: Session = Depends(get_db)):
    """
    Eliminar actividad y renumerar si es obligatoria
    
    Si la actividad eliminada era obligatoria, renumera automáticamente
    las actividades restantes para mantener el orden consecutivo.
    """
    # Obtener la actividad antes de eliminar para verificar si era obligatoria
    activity = crud.get_activity_type_by_id(db, id_activity_type)
    if not activity:
        Exceptions.register_not_found("Activity type", id_activity_type)
    
    deleted_order = activity.activity_order if activity.mandatory else None
    
    # Eliminar la actividad
    success = crud.delete_activity_type(db, id_activity_type)
    if not success['deleted']:
        if success['elimination_allow']:
            Exceptions.register_not_found("Activity type", id_activity_type)
        else:
            Exceptions.conflict_with_register("Activity type", id_activity_type)
    
    # Renumerar si era obligatoria
    if deleted_order:
        crud.renumber_mandatory_activities_after_delete(db, deleted_order)
    
    return {"message": "Activity type deleted successfully"}
```

---

## Pasos de Implementación

### Paso 1: Actualizar schemas

**Archivo:** `app/schemas/activityType.py`

1. Cambiar `mandatory: bool = Field(None, ...)` a `mandatory: bool = Field(..., ...)`
2. Cambiar `activity_order: int = Field(None, ...)` a `activity_order: int = Field(0, ...)`
3. Agregar `@validator('activity_order')` con las reglas de validación
4. Agregar clases `ActivityTypeReorder` y `ActivityTypeBatchReorder`

**Archivo:** `app/schemas/__init__.py`

5. Actualizar línea 2 para incluir `ActivityTypeBatchReorder`

### Paso 2: Agregar funciones CRUD

**Archivo:** `app/crud/activityType.py`

1. Agregar función `batch_reorder_mandatory_activities()`
2. Agregar función `renumber_mandatory_activities_after_delete()`

**Nota:** No requiere cambios en `app/crud/__init__.py` porque usa `from .activityType import *`

### Paso 3: Actualizar endpoints API

**Archivo:** `app/api/activityType.py`

1. Agregar import de `ActivityTypeBatchReorder` desde `app.schemas`
2. Agregar import de `HTTPException, status` desde `fastapi`
3. Agregar nuevo endpoint `PUT /reorder/`
4. Modificar endpoint `DELETE /{id_activity_type}` para incluir renumeración

**Nota:** No requiere cambios en `app/api/__init__.py` ni `app/main.py` porque el router ya está registrado.

### Paso 4: Validación manual

Ejecutar el backend y probar con curl/Postman:

```bash
# 1. Probar validación del schema
curl -X POST http://localhost:8003/activity_type/ \
  -H "Content-Type: application/json" \
  -d '{"activity": "Test", "mandatory": true, "category": "test", "activity_order": 0}'
# Esperado: 422 Unprocessable Entity (validation error)

# 2. Probar reordenamiento
curl -X PUT http://localhost:8003/activity_type/reorder/ \
  -H "Content-Type: application/json" \
  -d '{"activities": [{"id_activity_type": 1, "activity_order": 2}, {"id_activity_type": 2, "activity_order": 1}]}'
# Esperado: 200 OK con lista actualizada

# 3. Probar eliminación con renumeración
curl -X DELETE http://localhost:8003/activity_type/3
# Esperado: 200 OK, verificar que las actividades con order > 3 fueron decrementadas
```

---

## Archivos a Modificar

| Archivo | Acción | Líneas afectadas |
|---------|--------|------------------|
| `app/schemas/activityType.py` | Modificar | Todo el archivo (validación + nuevos schemas) |
| `app/schemas/__init__.py` | Modificar | Línea 2 (agregar `ActivityTypeBatchReorder`) |
| `app/crud/activityType.py` | Modificar | Agregar 2 funciones al final |
| `app/api/activityType.py` | Modificar | Agregar endpoint PUT, modificar DELETE |

---

## Dependencias

- **Base de datos:** Requiere que la migración `crm_db/migrations/XX_fix_activity_order.sql` haya sido ejecutada (constraint `chk_mandatory_order`)
- **Frontend:** El nuevo endpoint `PUT /activity_type/reorder/` será consumido por `ActivityTypeManagerView.vue`

---

## Riesgos y Consideraciones

1. **Validación duplicada:** El schema de Pydantic valida a nivel de aplicación, el constraint de BD valida a nivel de base de datos. Ambos son necesarios para defensa en profundidad.

2. **Transacciones atómicas:** Las funciones CRUD usan `try/except` con `rollback()` para garantizar atomicidad. Si falla una actualización, todas se revierten.

3. **Orden de operaciones en DELETE:** Primero se obtiene la actividad (para guardar su orden), luego se elimina, luego se renumera. Si el delete falla, no se ejecuta la renumeración.

4. **Compatibilidad con triggers:** Después de la renumeración en backend, el trigger `add_activities_from_activity_completed()` debe funcionar correctamente porque ya no habrá gaps en el orden.

5. **No se valida unicidad de orden:** El backend no valida que el orden sea único a nivel de aplicación (solo el constraint de BD lo hace para obligatorias). El endpoint `PUT /reorder/` valida que no haya duplicados en el request, pero no verifica contra la BD.
