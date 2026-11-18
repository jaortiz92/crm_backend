# Spec Backend: GET /budget/upload/status — Estado de Ingesta ETL

**ID de funcionalidad:** BE-S3-UPLOAD-STATUS
**Version:** 1.0 · **Fecha:** 2026-09-07
**Consumidor:** Centro de Ingesta del modulo presupuestal (`spec/04_Spec_frontend_upload_center.md`, seccion 7)
**Complejidad estimada:** BAJA (1-2 dias incluyendo smoke test)
**Convenciones obligatorias:** AGENTS.md (nomenclatura camelCase de archivos, checklist de registro, CRUD estilo `db.query`)

---

## 1. Objetivo

Proveer un unico endpoint que responda: **¿cuando fue la ultima carga exitosa de datos de cada ETL presupuestal?** para que el Centro de Ingesta muestre "Ultima carga: <fecha>" en cada una de sus 4 tarjetas (Costos, Gastos, Recibos, Cartera).

**Contexto verificado en el codigo actual (2026-09-07):**
- Las 4 tablas objetivo poseen `created_at = Column(DateTime, server_default=func.now())` y `source_file` (los ETLs la pueblan en el bulk insert).
- NO existe tabla de auditoria/historial de uploads, ni columna de atribucion de usuario en las 4 tablas (`uploaded_by`/`id_user` no existen).
- El router de uploads ya esta montado con prefijo `/budget/upload` en `app/api/budget/__init__.py`; **no se requiere tocar** `app/api/__init__.py` ni `app/main.py`.
- Cada ETL escribe en una unica transaccion con commit unico al final (Fase D); un 400/500 hace rollback completo. Por tanto: **filas presentes en la tabla == carga exitosa**, y `MAX(created_at)` es una aproximacion fiel de la ultima carga.

## 2. Contrato de API

| Atributo | Valor |
|---|---|
| Metodo | `GET` |
| Ruta | `/budget/upload/status` |
| Autenticacion | Bearer JWT (`Depends(get_current_user)`), identico a los 4 endpoints de upload |
| Parametros query | Ninguno |
| Body | Ninguno |
| Codigo exito | 200 |

### 2.1 Respuesta 200 — ejemplo

```json
{
  "actual_costs":          { "last_upload": "2026-09-05T18:32:11.123456" },
  "actual_expenses":       { "last_upload": null },
  "payment_ledger":        { "last_upload": "2026-08-30T09:15:02" },
  "accounts_receivable":   { "last_upload": "2026-09-04T21:44:59" }
}
```

### 2.2 Diccionario de campos

| Clave raiz | Tabla fuente | Modelo SQLAlchemy | `last_upload` |
|---|---|---|---|
| `actual_costs` | `actual_costs` | `ActualCost` (`app/models/budget/actualCost.py`) | `datetime` ISO-8601 o `null` |
| `actual_expenses` | `actual_expenses` | `ActualExpense` (`app/models/budget/actualExpense.py`) | `datetime` ISO-8601 o `null` |
| `payment_ledger` | `payment_ledger` | `PaymentLedger` (`app/models/budget/paymentLedger.py`) | `datetime` ISO-8601 o `null` |
| `accounts_receivable` | `accounts_receivable` | `AccountReceivable` (`app/models/budget/accountReceivable.py`) | `datetime` ISO-8601 o `null` |

`null` = la tabla esta vacia (nunca hubo carga con registros). Sin paginacion, sin orden garantizado de claves.

### 2.3 Codigos de error

| Codigo | Condicion |
|---|---|
| 401 / 403 | Token ausente/invalido/expirado (comportamiento estandar de `get_current_user`; el frontend lo resuelve por interceptor global) |
| 500 | Solo fallos de infraestructura (DB caida). Sin validaciones de negocio propias. |

## 3. Fuente de datos (decision de diseño APROBADA)

**Decision del stakeholder:** derivar de `MAX(created_at)` sobre las tablas existentes (opcion minima). **NO** crear tabla `upload_log`, **NO** modificar los 4 ETLs.

SQL equivalente (4 agregaciones independientes en la misma request):

```sql
SELECT MAX(created_at) FROM actual_costs;
SELECT MAX(created_at) FROM actual_expenses;
SELECT MAX(created_at) FROM payment_ledger;
SELECT MAX(created_at) FROM accounts_receivable;
```

### 3.1 Limitaciones aceptadas para v1

1. **Zona horaria:** `created_at` es `func.now()` del servidor PostgreSQL (UTC en docker-compose). Se devuelve naive-ISO tal cual, consistente con el resto del proyecto; el frontend formatea a local.
2. Una carga que insertara **0 registros validos** no refrescaria el estado (no deja filas). Caso patologico ya que todo upload 200 inserta >= 1 fila; aceptado.
3. **No se puede reportar quien subio el archivo** (no hay columna de usuario). Si gerencia exige auditoria formal, ver seccion 8 (v2).
4. El diseno de respuesta con **objeto anidado por dataset** permite anadir despues `source_file`, `records`, `forced` o campos v2 **sin romper** el contrato del frontend. No agregar hoy (decision explicita: respuesta minima).

## 4. Plan de implementacion (checklist de convenciones del proyecto)

3 archivos nuevos/mificados, 2 registros en `__init__.py`. Sin modelo nuevo (nada de `create_all`).

### Paso 1 — Schema: nuevo `app/schemas/budget/uploadStatus.py`

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DatasetUploadStatus(BaseModel):
    last_upload: Optional[datetime] = None


class UploadStatusResponse(BaseModel):
    actual_costs: DatasetUploadStatus
    actual_expenses: DatasetUploadStatus
    payment_ledger: DatasetUploadStatus
    accounts_receivable: DatasetUploadStatus
```

Registro: **import nominal explicito** en `app/schemas/budget/__init__.py`:
`from .uploadStatus import DatasetUploadStatus, UploadStatusResponse`
y re-export en el bloque budget de `app/schemas/__init__.py` (segun el patron actual del archivo).

### Paso 2 — CRUD: nuevo `app/crud/budget/uploadStatus.py`

```python
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.budget.actualCost import ActualCost
from app.models.budget.actualExpense import ActualExpense
from app.models.budget.paymentLedger import PaymentLedger
from app.models.budget.accountReceivable import AccountReceivable


def get_upload_status(db: Session) -> dict:
    """MAX(created_at) por dataset ETL. None si la tabla esta vacia."""
    return {
        "actual_costs": {"last_upload": db.query(func.max(ActualCost.created_at)).scalar()},
        "actual_expenses": {"last_upload": db.query(func.max(ActualExpense.created_at)).scalar()},
        "payment_ledger": {"last_upload": db.query(func.max(PaymentLedger.created_at)).scalar()},
        "accounts_receivable": {"last_upload": db.query(func.max(AccountReceivable.created_at)).scalar()},
    }
```

**Nota:** ajustar los imports de modelos al patron exacto que ya usan los archivos hermanos de `app/crud/budget/` (revisar `actualCost.py` CRUD antes de escribir).

Registro: `from .uploadStatus import *` en `app/crud/budget/__init__.py`.

### Paso 3 — Endpoint: anadir a `app/api/budget/upload.py` (archivo existente)

```python
@router.get("/status", response_model=UploadStatusResponse)
def get_upload_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ultima fecha de carga ETL por dataset (null si nunca se cargo)."""
    return crud.get_upload_status(db)
```

- Importar `UploadStatusResponse` via `from app.schemas import ...` (bloque budget).
- Funcion `def` sincrona (estilo CRUD legacy), no `async def` (no lee archivos).
- Sin conflicto de rutas: `/status` es GET y los uploads son POST sobre otras sub-rutas.
- **Sin cambios** en `app/api/budget/__init__.py`, `app/api/__init__.py` ni `app/main.py`.

## 5. Rendimiento

- 4 agregaciones `MAX()` con sequential scan (`created_at` no indexado). Con volumenes actuales (< 500k filas) cada una < 50 ms.
- **Gatillo de revision:** si alguna tabla supera ~1M de filas, agregar `Index("ix_<tabla>_created_at", "created_at")` en el modelo (auto-creado por `create_all`, sin migraciones). No requerido para entregar.
- Sin cacheo en v1. Frecuencia esperada: 1-2 llamadas por sesion de usuario + 1 por carga.

## 6. Criterios de aceptacion

Nuevo smoke test: **`crm_backend/test/test_upload_status_smoke.py`**, siguiendo el patron de los tests `test_*_smoke.py` existentes en este directorio.

| AC | Criterio |
|---|---|
| AC-1 | GET sin token / token invalido -> 401 o 403 (el que use el proyecto hoy) |
| AC-2 | GET autenticado -> 200 con exactamente 4 claves raiz: `actual_costs`, `actual_expenses`, `payment_ledger`, `accounts_receivable` |
| AC-3 | Cada clave raiz contiene un objeto con unica propiedad `last_upload`: datetime ISO-8601 parseable o `null` |
| AC-4 | Tablas vacias -> los 4 `last_upload` son `null` |
| AC-5 | Tras un `POST /budget/upload/accounts-receivable` existoso (usar fixture `data/` que ya usan los smoke tests de cartera) -> `accounts_receivable.last_upload` no es null y esta dentro de +/- 5 min de la hora del servidor |
| AC-6 | Regresion: el nuevo endpoint no altera el comportamiento de los 4 endpoints de upload (misma firma de respuestas 200/400) |
| AC-7 | Dos llamadas consecutivas devuelven el mismo payload (endpoint idempotente, solo lectura) |

## 7. Fuera de alcance

- Historial/paginado de cargas anteriores.
- Atribucion de usuario que subio, flag `forced`, conteo de filas por carga, `source_file` en la respuesta (decision de diseno: v1 minima).
- Estado de los endpoints `/cost-centers` (TODO pendiente) ni `budget-plan-income` / `budget-plan-expense`: no forman parte de las 4 tarjetas del Centro de Ingesta.

## 8. Backlog v2 (contexto, NO implementar ahora)

Auditoria formal: tabla `upload_log` (`uploaded_at`, `dataset`, `source_file`, `id_user`, `records_inserted`, `forced`) + logging de 1 linea en cada ETL. Queda como decision registrada porque la opcion fue evaluada y descartada a favor de la derivacion minima (seccion 3). El contrato de `UploadStatusResponse` ya es compatible hacia adelante con este v2 gracias al anidamiento por dataset.