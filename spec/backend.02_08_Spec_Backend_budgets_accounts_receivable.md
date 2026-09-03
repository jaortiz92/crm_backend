# Especificación Técnica: ETL accounts-receivable (Estado de Cartera)

| Campo | Valor |
| :--- | :--- |
| **Documento** | Spec ETL Accounts Receivable — Estado de Cuenta 30-60-90 (SIIGO) |
| **Módulo** | `budget` → tabla `accounts_receivable` |
| **Versión** | 1.0 (consolidada) |
| **Fecha** | 2026-09-01 |
| **Estado** | Aprobada para implementación |
| **Origen** | `EstadoCuenta306090.xlsx` (export cartera SIIGO) |
| **Patrón** | 4 fases ETL transaccionales + reemplazo atómico (*atomic upsert*) + cierre por marcaje PAID |
| **Fuentes analizadas** | `app/models/budget/accountReceivable.py`, `app/schemas/budget/accountReceivable.py`, `app/crud/budget/accountReceivable.py`, `app/utils/templates/budgetTemplates.py`, `app/api/budget/upload.py`, `app/api/budget/accountReceivable.py`, `app/models/customer.py`, `app/models/contact.py`, `app/models/invoice.py`, archivo de ejemplo en `crm_backend/test/data/EstadoCuenta306090.xlsx` |

> **⚠️ Aviso de cambios frente al borrador original**: este documento **rechaza la premisa del borrador §4 "No se requieren migraciones"**. Por decisiones del stakeholder (Decisiones D-1 y D-3) se agregan **3 columnas nuevas** a `accounts_receivable` que requieren `ALTER TABLE` manual (el proyecto usa `Base.metadata.create_all`, que **no** añade columnas a tablas existentes). Ver §4.3.

---

## 0. Decisiones registradas (Decision Log)

| ID | Decisión | Origen |
| :--- | :--- | :--- |
| **D-1** | Trazabilidad del documento: se persisten **dos columnas nuevas**: `customer_document` (Float, raíz numérica) e `identification_original` (String(50), texto crudo del Excel). | Pregunta 1/3 → opción 3 |
| **D-2** | Sincronización del snapshot: **marcar PAID, no borrar**. Los documentos que desaparecen de un archivo nuevo se cierran con `status=PAID, paid_amount=balance_previo, balance=0`. El reemplazo por `document_number` se mantiene. | Pregunta 2/3 → opción 2 |
| **D-3** | Guarda contra archivo viejo: columna nueva `statement_date` (Date) + comparación de fechas de corte. Archivo con corte anterior al almacenado ⇒ `HTTP 400`, salvo Form param `force=true`. | Pregunta 3/3 → opción 1 |
| **D-4** | Cruce de cliente con **fallback a `contacts`**: si la raíz no está en `customers.document`, se busca en `contacts.document`; si aparece, se asigna el `contact.id_customer` (nunca `id_contact`). Prioridad: customer > contact. | Feedback del stakeholder al supuesto 1 |
| **D-5** | Pagos/cobros **no** se reconcilian contra `payment_ledger` automáticamente (descartada la opción 4 de D-2): los pagos se cruzan vía CRUD manual de `PaymentLedger` (`id_account_receivable` se llena a mano, igual que en el ETL de payment-ledger). | Implícito en D-2 |

Supuestos del stakeholder aceptados sin cambios (del flujo de definición):

- **A-2**: se relaja `ge=0` en `total_amount` y `paid_amount` del schema Pydantic (56 filas negativas en el archivo real; mínimo −5,657,816).
- **A-3**: documentos duplicados dentro del archivo (`FVFE1595` ×2, `NC559-...` ×2 → 121 filas / 119 documentos distintos) se insertan como filas separadas; si `invoice_number` resuelve a varias cuotas, ambas se vinculan al `id_invoice` de menor `key`.
- **A-4**: los recibos `rc` (51 filas) **sí** entran a cartera con `id_invoice = NULL`.
- **A-5**: `legacy_debt_records` = **toda** fila con `id_invoice = NULL` (incluye rc/NC/DMC/NO). El `42` del borrador es ilustrativo, no valor de verdad.
- **A-6**: el endpoint orquesta las fases llamando métodos de `BudgetTemplates`; la clase no hace `commit` hasta la Fase D (patrón payment-ledger/actual-expenses).
- **A-7**: el stub actual `process_estado_cuenta()` se **elimina** y es reemplazado por la tubería de este documento.
- **A-8**: el DELETE por documento usa el prefijo ya montado: `/budget/account-receivable/by-document/{document_number}` (singular). 0 coincidencias ⇒ 404.
- **A-9**: aging por cascada estricta sobre columnas del Excel; ningún bucket ≠ 0 ⇒ `NULL`.
- **A-10**: validaciones bloqueantes adicionales: fechas inválidas, DataFrame vacío, extensión no `.xlsx`, corte no parseable.

---

## 1. Objetivo del Proceso (*Process Objective*)

Establecer la tubería ETL que procesa el reporte de cartera ("Estado de Cuenta 30-60-90") y mantiene la tabla `accounts_receivable` como **espejo de la deuda viva** del CRM, con tres garantías:

1. **Reemplazo atómico por documento**: recargar el mismo archivo (o una versión actualizada del mismo corte) no duplica ni corrompe datos; todo ocurre en una única transacción (*all-or-nothing*).
2. **Cierre semántico de deuda (*snapshot sync*)**: un documento que deja de aparecer en un estado de cuenta más reciente se marca `PAID` con su saldo consumido (quedó pagado o el RC fue aplicado), conservando trazabilidad auditable en la tabla.
3. **Cartera Migrada (*Legacy Debt*)**: documentos del estado de cuenta que no existen físicamente en el CRM (facturas pre-CRM, recibos, notas de ajuste) se registran con `id_invoice = NULL`, garantizando visibilidad total del flujo de caja esperado.

**Fuera de alcance**: cálculos de `PaymentLedger` (libro de pagos) sobre estos registros, conciliación automática de pagos, frontend de carga (se especifica en documento aparte), histórico multi-corte (cada subida refleja un solo corte vigente).

---

## 2. Glosario

| Término | Definición |
| :--- | :--- |
| **Documento (`document_number`)** | Identificador del título de crédito en cartera: concatenación normalizada de columnas `Doc` + `Num` del Excel, sin espacios. Ej: `"FV"` + `"FE 1544"` → `"FVFE1544"`. |
| **Raíz de identificación** | Primera secuencia de dígitos del texto `Identificacion` del Excel. Ej: `"NIT 900576607 - 7"` → `"900576607"`. |
| **Legacy Debt (*Cartera Migrada*)** | Fila de cartera con `id_invoice = NULL`: el documento existe en SIIGO pero no en la tabla `invoices` del CRM. |
| **Contact fallback** | Resolución del dueño del documento a través de `contacts.document` cuando la raíz no está en `customers.document`, asignando el `id_customer` del contacto. |
| **Fecha de corte (*statement_date*)** | Fecha de expedición del estado de cuenta, embebida en la fila 2 del Excel (`"…fecha de corte 26/08/2026"`). Define la vigencia del snapshot. |
| **Cierre (*close/settle*)** | Transición `OPEN → PAID` con `balance = 0` aplicada a documentos que desaparecen del snapshot. |
| **Aging bucket (snapshot)** | Tramo de mora **declarado por el propio Excel** (una de las 5 columnas de rango con valor ≠ 0), no calculado por fecha del sistema. |

---

## 3. Arquitectura y puntos de integración

### 3.1 Diagrama de flujo

```
 Cliente (multipart .xlsx)
        │
        ▼
 POST /budget/upload/accounts-receivable        app/api/budget/upload.py
        │  1. valida extensión .xlsx            (reemplaza stub TODO)
        │  2. BytesIO → BudgetTemplates
        ▼
 ┌────────────────────────────────────────────────────────────────┐
 │ Fase A  etl.process_accounts_receivable()                      │  pandas puro
 │   read(header=3) · parse corte · quita subtotales · doc number │  sin DB
 │   raíz de identificación · casts numéricos/fecha               │
 ├────────────────────────────────────────────────────────────────┤
 │ Guarda de corte (dentro de Fase C, requiere lectura DB)        │
 │   corte < MAX(statement_date) y NOT force → 400                │
 ├────────────────────────────────────────────────────────────────┤
 │ Fase B  etl._map_accounts_receivable_relational_data(db)       │  3 consultas
 │   customers.document → contacts.document (fallback) → id_cust  │  batch +
 │   invoices.invoice_number → id_invoice (min key) o NULL        │  UPDATE cierre
 │   aging_bucket por cascada de columnas                         │
 ├────────────────────────────────────────────────────────────────┤
 │ Fase C1 etl._validate_accounts_receivable_integrity(db)        │
 │   clientes no resueltos → 400 (listado) · fechas · vacío       │
 ├────────────────────────────────────────────────────────────────┤
 │ Fase C2 etl._handle_accounts_receivable_duplicates(db)         │  sin commit
 │   NULLIFY payment_ledger.id_account_receivable afectados       │  (misma trans.)
 │   DELETE accounts_receivable WHERE document_number IN (file)   │
 ├────────────────────────────────────────────────────────────────┤
 │ Fase C3 etl._close_settled_accounts_receivable(db, docs)       │  sin commit
 │   UPDATE OPEN ∧ doc ∉ file → PAID · paid=balance · balance=0   │
 ├────────────────────────────────────────────────────────────────┤
 │ Fase D  etl._bulk_insert_accounts_receivable(db, filename)     │  ÚNICO commit
 │   AccountReceivableCreate[] → crud.create_accounts_receivable  │
 │   _bulk (existente, hace commit)                               │
 └────────────────────────────────────────────────────────────────┘
        │  cualquier excepción → db.rollback() → 400/500
        ▼
 200 JSON resumen (§6.1)
```

### 3.2 Archivos a modificar (checklist de implementación)

| # | Archivo | Cambio |
| :-- | :--- | :--- |
| 1 | `app/models/budget/accountReceivable.py` | + 3 columnas (`customer_document`, `identification_original`, `statement_date`). §4.3. |
| 2 | BD (todas las instancias: dev Docker y prod) | `ALTER TABLE` manual único. §4.3.1. |
| 3 | `app/schemas/budget/accountReceivable.py` | + 3 campos; quitar `ge=0` de `total_amount`/`paid_amount`; default `status` de `"open"` a `"OPEN"`. §4.4. |
| 4 | `app/crud/budget/accountReceivable.py` | + 4 funciones (delete por lista sin commit, cierre sin commit, delete por documento con commit, nullify de FK). §7. |
| 5 | `app/utils/templates/budgetTemplates.py` | Eliminar `process_estado_cuenta()`; agregar 5 métodos + 5 contadores; helper de parseo de corte. §5. |
| 6 | `app/api/budget/upload.py` | Implementar `upload_accounts_receivable` (hoy stub TODO), con `force: bool = Form(False)`. §6.1. |
| 7 | `app/api/budget/accountReceivable.py` | + ruta `DELETE /by-document/{document_number}`. §6.2. |

No se tocan: `app/main.py`, `app/api/__init__.py`, `app/api/budget/__init__.py` (los routers ya están registrados), `budgetEngine.py` (compatible, ver §8.4).


---

## 4. Estructura de Datos de Entrada y Cambios de Esquema

### 4.1 Archivo fuente (verificado contra `EstadoCuenta306090.xlsx`)

- **Nombre**: `EstadoCuenta306090.xlsx` (los nombres reales variarán: solo `.xlsx` es obligatorio; el nombre se persiste en `source_file`).
- **Formato**: Excel `.xlsx`, motor `openpyxl`.
- **Header**: fila 4 de Excel ⇒ `header=3` en pandas (equivalente a `skiprows=3`).
- **Estructura verificada (276 filas crudas × 21 columnas; 121 filas de detalle + 155 subtotales)**:

| Columna Excel (literal) | Tipo real | Uso en ETL |
| :--- | :--- | :--- |
| `Nombres` | object | Nombre del cliente (solo para mensajes de error; no se persiste) |
| `Identificacion` | object | Raíz de identificación + texto crudo. **Contiene prefijo y dígito**: `"NIT 900576607 - 7"`, `"CC 1043635944 -"` |
| `Doc` | object | Prefijo de documento. Valores en muestra: `FV`(58), `rc`(51, minúsculas), `NC`(9), `DMC`(2), `NO`(1). **Nulo en las 155 filas de subtotales** |
| `Num` | object | Número con formato libre: `"FE 1544"`, `"2468"`, `"510 - PARTIDAS CONCILIATORIAS"` |
| `Fecha Vence` | datetime64 | `due_date` (0 nulos en muestra) |
| `Valor Total` | float64 | `total_amount` y `balance`. **56 filas negativas**, min −5,657,816; suma detalle = **439,696,679.72** |
| `Por Vencer`, `1 A 30`, `31 A 60`, `61 A 90`, `Más De 90` | int/float64 | Snapshot de aging. **Verificado: cada fila de detalle tiene exactamente un bucket ≠ 0** |
| `NumDias` | int64 | No se usa (el aging se toma de las columnas de rango) |

> ⚠️ **Nombres con acentos**: `'Más De 90'` usa `á` (U+00E1) y `'Dirección'` igual. El código debe referenciar el nombre exacto con acento o normalizar; nunca `'Mas De 90'`.

### 4.2 Parsing de la fecha de corte

Fila 2 del Excel (celda A2, `header=None` fila índice 1):
`"Estado de Cuenta 30-60-90 con fecha de corte 26/08/2026 "`

- **Regex**: `r'fecha de corte\s+(\d{1,2}/\d{1,2}/\d{4})'`, case-insensitive, sobre `str(raw.iloc[1, 0])`.
- **Parseo**: `pd.to_datetime(match, format='%d/%m/%Y').date()` → `datetime.date(2026, 8, 26)`.
- **Implementación**: lectura ligera adicional `pd.read_excel(self.file, engine='openpyxl', header=None, nrows=3)` + `self.file.seek(0)` antes de la lectura principal (BytesIO consumido).
- **Fallo de parseo** (archivo de otro formato): `HTTP 400` bloqueante — el snapshot exige corte conocido para gobernar la guarda D-3.

### 4.3 Cambios a la tabla `accounts_receivable` (D-1, D-3) — **SÍ requiere ALTER manual**

Nuevas columnas en `AccountReceivable` (todas **nullable** — las filas existentes no se backfillean):

| Columna | Tipo SQLAlchemy | Tipo Postgres | Regla |
| :--- | :--- | :--- | :--- |
| `customer_document` | `Column(Float)` | `FLOAT` | Raíz numérica extraída, casteada a float. Permite JOIN con `customers.document` / `contacts.document` (ambas Float). |
| `identification_original` | `Column(String(50))` | `VARCHAR(50)` | Texto crudo de `Identificacion` tal cual. Verificado: máx 18 chars. |
| `statement_date` | `Column(Date)` | `DATE` | Corte parseado del archivo (§4.2). Gobernar guarda D-3 y análisis por corte. |

#### 4.3.1 Script de migración (ejecutar una vez por ambiente antes de desplegar)

```sql
ALTER TABLE accounts_receivable
    ADD COLUMN IF NOT EXISTS customer_document      FLOAT,
    ADD COLUMN IF NOT EXISTS identification_original VARCHAR(50),
    ADD COLUMN IF NOT EXISTS statement_date          DATE;

-- Opcional (recomendado si la tabla crece; innecesario a 121 filas):
-- CREATE INDEX IF NOT EXISTS ix_accounts_receivable_document_number
--     ON accounts_receivable (document_number);
```

Justificación: el proyecto no usa Alembic; `create_all` solo crea tablas nuevas, nunca añade columnas a existentes. Sin este ALTER, la inserción ETL falla con `UndefinedColumn` ⇒ 500.

#### 4.3.2 Modelo (adición literal tras `source_file`)

```python
# app/models/budget/accountReceivable.py  (dentro de class AccountReceivable)
    source_file = Column(String(200))
    # --- Nuevas: trazabilidad D-1 y snapshot D-3 ---
    customer_document = Column(Float)                    # raíz numérica de Identificacion (JOIN-able)
    identification_original = Column(String(50))         # crudo del Excel p.ej. "NIT 900576607 - 7"
    statement_date = Column(Date)                        # fecha de corte del estado de cuenta
```

### 4.4 Cambios al schema Pydantic `AccountReceivableCreate/AccountReceivable` (A-2, D-1, D-3)

```python
# app/schemas/budget/accountReceivable.py  (AccountReceivableBase)
    total_amount: float = Field(..., description="Total amount (puede ser negativo: saldos a favor)")   # se quita ge=0
    paid_amount: Optional[float] = Field(0, description="Amount paid so far")                           # se quita ge=0 (cierre con balance negativo)
    status: Optional[str] = Field("OPEN", description="Status: OPEN, PARTIAL, PAID")                     # default corregido a mayúsculas (enum BD es 'OPEN'; "open" quebraba insert manual)
    customer_document: Optional[float] = Field(None, description="Numeric root of customer identification from source file")
    identification_original: Optional[str] = Field(None, max_length=50, description="Raw identification text from source file")
    statement_date: Optional[date] = Field(None, description="Statement cutoff date")
```

**Sin cambios**: `aging_bucket` (`String(20)` del modelo cubre `over_90` = 7 chars), `document_number` (`String(50)`, máximo verificado 28), `id_customer`/`id_invoice` (ya `Optional`), enum `ReceivableStatusEnum` (ya existe `PAID`), FKs, relaciones. El modelo ya soportaba `id_invoice` opcional (Patrón Legacy Debt sin cambios estructurales adicionales).

**Nota de consistencia**: `crud.create_accounts_receivable_bulk` y `create_account_receivable` usan `Model(**schema.model_dump())`; al añadir los 3 campos al schema, el bulk los persiste sin tocar el CRUD de inserción.

### 4.5 Reglas de transformación de datos (maestro)

| Campo destino | Origen | Transformación |
| :--- | :--- | :--- |
| `document_number` | `Doc` + `Num` | `(Doc + ' ' + Num)` → `str.replace(r'\s+', '', regex=True)`. Mayúsculas **preservadas** (`'rc2468'` se guarda tal cual). Si `Num` es nulo ⇒ solo `Doc`. |
| `id_customer` | raíz → `customers.document` → `contacts.document` | §5.2.1–5.2.2. **Nunca NULL** al insertar (validación bloqueante §5.3.1). |
| `id_invoice` | `document_number` → `invoices.invoice_number` | Coincidencia exacta post-normalización; multi-cuota ⇒ menor `key` (A-3); ausente ⇒ `NULL` (Legacy Debt). |
| `customer_document` | raíz `str.extract(r'(\d+)')` | `float()` de la raíz. |
| `identification_original` | `Identificacion` | Crudo, `str.strip()`. |
| `due_date` | `Fecha Vence` | `pd.to_datetime(...).dt.date`. NaT ⇒ 400 (§5.3.3). |
| `total_amount` | `Valor Total` | `pd.to_numeric`. **Negativos permitidos** (A-2). |
| `paid_amount` | — | `0` fijo en inserción. Los pagos se reflejan vía CRUD manual de `PaymentLedger` (D-5). |
| `balance` | `Valor Total` | Copia directa (soporta negativos = saldos a favor). Invariante: `balance = total_amount − paid_amount` en toda fila ETL. |
| `status` | — | Literal `"OPEN"` (asignación en duro, fase de inserción). |
| `aging_bucket` | columnas de rango | Cascada §5.2.4. |
| `source_file` | `UploadFile.filename` | Tal cual. |
| `statement_date` | fila 2 del Excel | §4.2. **Toda fila del archivo recibe el mismo corte del archivo.** |


---

## 5. Especificación Funcional — Pipeline de 4 Fases

Todos los métodos viven en `BudgetTemplates` (`app/utils/templates/budgetTemplates.py`). El stub existente `process_estado_cuenta()` se **elimina** (A-7); el helper privado `_compute_aging_buckets()` queda marcado deprecado y **sin uso** en esta tubería (sus valores `30/60/90+` no corresponden al vocabulario de snapshot).

Nuevos contadores en `__init__` (patrón de los contadores de payment-ledger):

```python
self.ar_rows_excluded_subtotals: int = 0
self.ar_contact_fallback_resolved: int = 0     # filas resueltas vía contacts (D-4)
self.ar_legacy_debt_records: int = 0           # filas con id_invoice NULL (A-5)
self.ar_rows_closed: int = 0                   # filas marcadas PAID (D-2)
self.ar_statement_date: Optional[date] = None  # corte parseado (guarda + respuesta)
```

### 5.1 Fase A — `process_accounts_receivable() -> DataFrame` (limpieza, sin DB)

1. **Parsear corte** (§4.2) antes de la lectura principal → `self.ar_statement_date`. Fallo ⇒ `HTTPException 400` `"No statement cutoff date found in file (expected '... fecha de corte DD/MM/YYYY' in row 2)"`.
2. **Cargar**: `self.df = pd.read_excel(self.file, engine="openpyxl", header=3)`; `self.total_rows_raw = len(self.df)`.
3. **Eliminar subtotales** (BR-1): quitar filas donde `Doc` es nulo o cadena vacía tras `strip()`. Contar en `self.ar_rows_excluded_subtotals`. (Muestra: 276 − 155 = 121.)
4. **`document_number`** (BR-2, §4.5): concatenación limpia; resultado `str`, sin espacios internos ni extremos.
5. **Raíz de identificación** (BR-3): `self.df['identification_root'] = self.df['Identificacion'].astype(str).str.extract(r'(\d+)')[0]` (primera racha de dígitos: descarta prefijo NIT/CC y dígito de verificación). Sin dígitos ⇒ `NaN` ⇒ treated as cliente no resuelto (§5.3.1).
6. **Cast**: `Fecha Vence` → `pd.to_datetime(errors='coerce').dt.date`; `Valor Total` y las 5 columnas de rango → `pd.to_numeric(errors='coerce')` (el dtype de `'Más De 90'` es float en algunas filas: nunca comparar enteros estrictos).
7. Si el DataFrame queda vacío ⇒ `HTTPException 400` `"No valid detail rows found (all rows were subtotals or the file structure changed)"`.

### 5.2 Fase B — `_map_accounts_receivable_relational_data(db) -> DataFrame`

#### 5.2.1 Resolución de cliente — paso 1: `customers.document` (batch)

```python
roots = {float(r) for r in self.df['identification_root'].dropna().unique()}
cust_map = {doc: id_customer for id_customer, doc in
            db.query(CustomerModel.id_customer, CustomerModel.document)
              .filter(CustomerModel.document.in_(list(roots))).all()}
```

#### 5.2.2 Resolución de cliente — paso 2: fallback `contacts.document` (D-4, batch)

Para raíces **no** resueltas en 5.2.1:

```python
contact_map = {doc: id_customer for id_customer, doc in
               db.query(ContactModel.id_customer, ContactModel.document)
                 .filter(ContactModel.document.in_(missing_roots)).all()}
```

- Hit ⇒ `id_customer = contact_map[root]`; **nunca** se persiste `id_contact`; se incrementa `self.ar_contact_fallback_resolved`.
- **Precedencia**: si una raíz vive simultáneamente como `customers.document` de X y `contacts.document` de Y, gana **X** (customer primero). Documento único garantizado por índices `unique=True` en ambas tablas.
- Nota: el contacto puede estar inactivo; la resolución **no** filtra por `active` (comercial: documento heredado).

#### 5.2.3 Resolución de factura — `invoices.invoice_number` (flexible, batch)

```python
rows = db.query(InvoiceModel.invoice_number, InvoiceModel.key, InvoiceModel.id_invoice) \
         .filter(InvoiceModel.invoice_number.in_(docs)).all()
# number -> (key, id_invoice) conservando el MENOR key (A-3, regla del payment-ledger)
```

- Hit ⇒ `id_invoice`; miss ⇒ `id_invoice = NULL` y `self.ar_legacy_debt_records += 1`.
- `document_number` ya llega normalizado de Fase A (`"FVFE1544"`), igual que `invoices.invoice_number` convención del ETL de costos (`_clean_document`); **no** se aplican variantes `{n, "FVFE"+n}` como en payment-ledger: aquí el número se construye, no se imputa desde texto libre.
- Prefijos `rc/NC/DMC/NO`: se intentan igual (no hay razón para excluirlos); hoy no existen en `invoices` ⇒ NULL ⇒ legacy.

#### 5.2.4 Aging bucket — cascada snapshot (BR-6, A-9)

Evaluación **ordenada**; gana el primer bucket ≠ 0 (con `fillna(0)` previo):

| Orden | Columna Excel | Valor `aging_bucket` |
| :-- | :--- | :--- |
| 1 | `Por Vencer` | `current` |
| 2 | `1 A 30` | `1_to_30` |
| 3 | `31 A 60` | `31_to_60` |
| 4 | `61 A 90` | `61_to_90` |
| 5 | `Más De 90` | `over_90` |
| — | todos = 0 | `NULL` (fallback defensivo; verificado: 0 casos en muestra) |

Aplica también a filas negativas (NC/ajustes con bucket declarativo). Implementación sugerida: `np.select` sobre las 5 máscaras `!= 0` en orden + `default=None`.

#### 5.2.5 Persistencia de trazabilidad

`self.df['customer_document'] = self.df['identification_root'].astype(float)` y `self.df['identification_original'] = self.df['Identificacion'].str.strip()` para **todas** las filas (independientemente de cómo se resolvió el cliente).

### 5.3 Fase C — Validaciones y reemplazo

#### 5.3.1 C1 `_validate_accounts_receivable_integrity(db)` (bloqueantes, A-10)

| # | Regla | Error |
| :-- | :--- | :--- |
| V1 | Existe al menos una fila con `id_customer` NULL (raíz no encontrada en customers **ni** en contacts, o raíz NaN) | `HTTP 400` — *No podemos rastrear deuda de clientes no registrados.* Detalle estructurado abajo. El endpoint hace `db.rollback()` ⇒ **no se inserta ni borra nada**. |
| V2 | `Fecha Vence` NaT tras cast | `HTTP 400` `"N records have invalid dates"` |
| V3 | **Guarda de corte (D-3)**: `nuevo_corte < db.query(func.max(AR.statement_date)).scalar()` y `force=false` | `HTTP 400` con ambos cortes (§6.1.3). `force=true` ⇒ continúa y la respuesta marca `"forced": true`. Corte igual o mayor ⇒ siempre permitido (idempotencia de recarga). |
| V4 | `total_amount` NaN (Valor Total no numérico) tras Fase A | `HTTP 400` `"N records have non-numeric amounts"` |

Detalle V1 (máx. 20 ejemplos, ordenado):

```json
{
  "detail": {
    "message": "Customers not found in catalog (checked customers.document and contacts.document)",
    "missing_count": 3,
    "missing_identifications": ["900111222", "12345678", "CC sin dígitos"],
    "examples": [{"identification": "900111222", "customer_name": "ALGUN_cliente SAS", "documents": ["FVFE1544"]}]
  }
}
```

> La guarda V3 se ejecuta en C1 **antes** de cualquier escritura (DELETE de C2). Orden estricto del endpoint: A → B → C1 → C2 → C3 → D.

#### 5.3.2 C2 `_handle_accounts_receivable_duplicates(db) -> int` (reemplazo atómico, sin commit)

1. `docs = self.df['document_number'].unique().tolist()` (muestra: 119).
2. **Integridad referencial**: antes de borrar, liberar punteros del libro de pagos:
   `UPDATE payment_ledger SET id_account_receivable = NULL WHERE id_account_receivable IN (SELECT id ... WHERE document_number IN docs)` — la FK `payment_ledger.id_account_receivable → accounts_receivable.id` **no tiene `ON DELETE`**; sin este paso el DELETE lanzaría `IntegrityError` si algún CRUD manual vinculó pagos. Implementación: obtener ids, luego `db.query(PaymentLedgerModel).filter(...in_(ids)).update({id_account_receivable: None}, synchronize_session=False)`.
3. `db.query(AR).filter(AR.document_number.in_(docs)).delete(synchronize_session=False)` — borra **OPEN y PAID** de esos documentos (un PAID que reaparece revive como OPEN con los datos nuevos — BR-14). Retorna `records_replaced` (filas, no documentos: recarga del archivo muestra ⇒ 121).
4. **Sin `commit`** — el caller controla la transacción (patrón `_handle_actual_expense_duplicates`).

#### 5.3.3 C3 `_close_settled_accounts_receivable(db, docs) -> int` (cierre por marcaje, D-2, sin commit)

```python
closed = db.query(AR).filter(
    AR.status == ReceivableStatusEnum.OPEN,
    AR.document_number.notin_(docs),
).update(
    {AR.status: ReceivableStatusEnum.PAID,
     AR.paid_amount: AR.balance,     # expresión SQL: saldo consumido = pagado
     AR.balance: 0},
    synchronize_session=False)
self.ar_rows_closed = closed
```

Reglas del cierre (BR-12):

- **Alcance**: solo `status='OPEN'` ∩ documento ausente del archivo. Las ya `PAID` no se re-tocan (idempotencia); las `PARTIAL` creadas a mano **no** se cierran (el cierre solo toca deuda que este ETL abrió).
- `aging_bucket` y `statement_date` **se conservan** como quedaron: la fila guarda el último corte en que se vio viva (semántica auditoría: *"el 26/08 seguía abierta en 1_to_30; el corte siguiente ya no aparecía"*).
- Balance negativo desaparecido ⇒ `paid_amount` negativo y `balance=0`; la invariante `total = paid + balance` se mantiene.
- Invariante de caja: los cierres aportan **0** al `SUM(balance)` que consume `budgetEngine` (§8.4).

### 5.4 Fase D — `_bulk_insert_accounts_receivable(db, source_filename) -> list`

Construye `AccountReceivableCreate` por fila (patrón iterrows de los demás ETLs) con `status="OPEN"`, `paid_amount=0`, `balance=total`, `statement_date=self.ar_statement_date`, `source_file=source_filename`, y los campos de trazabilidad. Delega en `crud.create_accounts_receivable_bulk` (**existente**, `bulk_save_objects` + `commit`) ⇒ único commit de la petición. Cualquier excepción posterior dispara `db.rollback()` en el endpoint.

### 5.5 Ciclo de vida del registro (state transitions)

```
                    ┌──────────────────────────────────────────────────┐
                    │            (nuevo documento en archivo)          │
                    ▼                                                  │
              ┌──────────┐   desaparece del archivo más nuevo ┌────────┴──┐
   upload ──▶ │   OPEN   │ ──────────────────────────────────▶ │   PAID    │
              └──────────┘   (paid=balance, balance=0)         └───────────┘
                    ▲                                              │
                    │  reaparece (con saldo renovado):             │
                    │  DELETE x documento (C2) + INSERT (D) ◀──────┘
                    │  ⇒ revive como OPEN fresh
                    │
   DELETE manual /by-document/{doc} o /{id}  ⇒  fila eliminada (de cualquier estado)
```

Regla de oro: **`accounts_receivable` = deuda viva del último corte + deuda cerrada por sincronización.** Un documento nunca se duplica: el par (documento, corte vigente) es único por construcción del ciclo C2+D.


---

## 6. Contratos de API

Autenticación en ambos endpoints: `Depends(get_current_user)` (JWT) — sin token válido ⇒ 401/403 estándar del proyecto.

### 6.1 `POST /budget/upload/accounts-receivable` (reemplaza el stub TODO actual)

**Request** `multipart/form-data`:

| Campo | Tipo | Req | Descripción |
| :--- | :--- | :-- | :--- |
| `file` | File | ✔ | `.xlsx` (guarda de extensión, mismo patrón que `/payment-ledger`: cualquier otra cosa ⇒ 400 `"Only .xlsx files are supported"`) |
| `force` | bool (Form) | ✘ (default `false`) | Sobrescribe la guarda de corte viejo (V3/D-3) |

**Orquestación del endpoint** (idéntica al patrón `upload_actual_expenses` / `upload_payment_ledger`):

```python
file_content = await file.read(); file_bytes = BytesIO(file_content)
try:
    etl = BudgetTemplates(file_bytes)
    df = etl.process_accounts_receivable()                            # A
    etl._map_accounts_receivable_relational_data(db)                  # B
    etl._validate_accounts_receivable_integrity(db, force=force)      # C1
    records_replaced = etl._handle_accounts_receivable_duplicates(db) # C2
    docs = df['document_number'].unique().tolist()
    records_closed = etl._close_settled_accounts_receivable(db, docs) # C3
    inserted = etl._bulk_insert_accounts_receivable(db, file.filename)# D (commit)
    return { ... §6.1.1 ... }
except HTTPException:
    db.rollback(); raise
except Exception as e:
    db.rollback(); raise HTTPException(500, f"Error processing accounts receivable: {str(e)}")
```

#### 6.1.1 Respuesta 200 (esquema; valores de ejemplo para el archivo muestra)

```json
{
  "message": "Accounts receivable uploaded successfully",
  "records_inserted": 121,
  "records_replaced": 121,
  "records_closed": 0,
  "source_file": "EstadoCuenta306090.xlsx",
  "statement_date": "2026-08-26",
  "forced": false,
  "details": {
    "total_rows_raw": 276,
    "rows_excluded_subtotals": 155,
    "total_outstanding_balance": 439696679.72,
    "legacy_debt_records": 51,
    "unique_customers": 77,
    "contact_fallback_resolved": 3
  }
}
```

Diccionario crudo (sin `response_model`), consistente con los demás uploads. Definiciones:

- `records_inserted`: filas creadas en D.
- `records_replaced`: **filas** borradas en C2 (≠ documentos: `FVFE1595` cuenta 2). Primera carga de un archivo nuevo ⇒ 0; recarga idéntica ⇒ 121. *(El `50` del borrador era ilustrativo.)*
- `records_closed`: filas OPEN→PAID en C3 (misma carga ⇒ 0; subidas posteriores con deuda pagada ⇒ ≥0).
- `statement_date`: corte del archivo procesado.
- `forced`: `true` si se aplicó un corte anterior con `force=true`.
- `total_outstanding_balance`: `round(float(df['Valor Total'].sum()), 2)` del detalle insertado.
- `legacy_debt_records`: filas con `id_invoice IS NULL` (A-5). Para la muestra con BD como está hoy: ≥ 51 (los `rc` nunca facturan) + facturas/NC anteriores al CRM. El `42` del borrador **no es un valor esperado**.
- `unique_customers`: `df['id_customer'].nunique()` (muestra: 77).
- `contact_fallback_resolved`: filas cuya raíz solo se encontró en `contacts.document` (D-4).

#### 6.1.2 Errores 400 (catálogo ver §10)

Respuestas con `detail` estructurado (V1, V3) o string plano (extensión, corte no parseable, fechas, importes, vacío) — mismo estilo de los ETLs existentes.

#### 6.1.3 Ejemplo de error de guarda de corte (V3)

```json
{
  "detail": {
    "message": "Stale statement file: cutoff 2026-08-19 is older than stored cutoff 2026-08-26. Marking documents as paid would produce false closures. Re-send with force=true to override.",
    "file_cutoff": "2026-08-19",
    "stored_cutoff": "2026-08-26"
  }
}
```

### 6.2 `DELETE /budget/account-receivable/by-document/{document_number}` (A-8)

> Corrección al borrador: el prefijo montado es **singular** (`app/api/budget/__init__.py`: `prefix="/account-receivable"`). Ruta de dos segmentos ⇒ sin colisión con `DELETE /{id_account_receivable}`.

- **Comportamiento**: elimina **todas** las filas (OPEN o PAID) con `document_number == {param}` exacto (case-sensitive). Útil para `FVFE1595` (2 filas ⇒ `records_deleted: 2`).
- **Integridad FK**: mismo nullify de `payment_ledger.id_account_receivable` que C2 (§5.3.2 paso 2) antes del DELETE, en la misma transacción.
- **0 coincidencias** ⇒ `Exceptions.register_not_found("AccountReceivable", document_number)` → **404** (patrón `actual-expense`).

**Respuesta 200**:

```json
{
  "message": "Accounts receivable deleted successfully",
  "records_deleted": 2,
  "document_number": "FVFE1595"
}
```

---

## 7. Contrato CRUD (altas en `app/crud/budget/accountReceivable.py`)

| Función | Firma | Transacción | Uso |
| :--- | :--- | :--- | :--- |
| `delete_accounts_receivable_by_documents` | `(db, document_numbers: List[str]) -> int` | **sin commit** | C2 (recibe el DF con ids ya nullified; el nullify puede vivir en la firma como helper privado) |
| `close_accounts_receivable_not_in` | `(db, document_numbers: List[str]) -> int` | **sin commit** | C3 |
| `nullify_payment_ledger_refs_for` | `(db, id_accounts_receivable: List[int]) -> int` | **sin commit** | C2 y endpoint §6.2 |
| `delete_accounts_receivable_by_document` | `(db, document_number: str) -> int` | **con commit** | Endpoint §6.2 (espejo de `delete_actual_expenses_by_document`) |

**Ya existentes, sin cambios**: `create_accounts_receivable_bulk` (usa `bulk_save_objects` + commit), CRUD por id. *Mejora opcional de endurecimiento (fuera del alcance crítico): aplicar el mismo nullify en `delete_account_receivable(db, id)` para que el borrado manual por id tampoco dispare `IntegrityError`.*

Importaciones de la clase template a adicionar: `AccountReceivable as AccountReceivableModel`, `ReceivableStatusEnum`, `PaymentLedger as PaymentLedgerModel`, `Contact as ContactModel` (el resto de modelos ya se importa).


---

## 8. Requisitos No Funcionales

### 8.1 Rendimiento y escalabilidad

- Escala objetivo: ≤ 5,000 filas de detalle por archivo (muestra: 121; 21 columnas). Todas las consultas relacionales son **batch** (4 lecturas + 1 UPDATE + 1 DELETE + 1 bulk INSERT), complejidad O(n) en consultas por subida — nunca por fila.
- Presupuesto: upload completo < 3 s en dev Docker (postura conservadora: el ETL de costos con 10× más filas es la referencia funcional).
- `NOT IN (docs)` con ~120 literales: aceptable en Postgres sin preparación de statement; el planner secuencializa sobre una tabla de miles de filas.

### 8.2 Seguridad

- Ambos endpoints exigen JWT (`get_current_user`); sin roles adicionales (coherente con el resto de uploads del módulo budget).
- Solo se lee el contenido del archivo en memoria (`BytesIO`); no se persiste en disco.
- Validación de extensión `.xlsx`; el parseo de `openpyxl` de un archivo malformado cae en el genérico 500 con rollback (sin leakage de rutas del servidor más allá del patrón actual del proyecto).

### 8.3 Transaccionalidad y consistencia (BR-14)

- **Todo o nada**: Fases C2+C3+D comparten la transacción de la petición; el único `commit` es en D (dentro del CRUD de inserción). Cualquier excepción ⇒ `db.rollback()` ⇒ ni deletes, ni cierres, ni inserts se materializan. El `rollback` restaura los registros borrados (propiedad ya demostrada por `_handle_actual_expense_duplicates`).
- Idempotencia: recarga del mismo archivo ⇒ estado final idéntico (§11 AC-4).
- Concurrencia: dos uploads simultáneos del mismo módulo no tienen lock dedicado; se asume operación secuencial (uso administrativo). Los DELETE/UPDATE de Postgres serializan por fila; en el peor caso uno de los dos termina con error de transacción → 500 + rollback → reintentar.

### 8.4 Compatibilidad aguas abajo (regression surface)

- `app/services/budgetEngine.py` (líneas ~88-92) proyecta caja sumando `SUM(balance)` por año de `due_date` **sin filtrar status**: los cierres D-2 ponen `balance = 0` ⇒ la proyección se auto-corrige al bajar la deuda pagada. Sin cambios necesarios. ✔
- Endpoints GET existentes: `AccountReceivable` response schema se ensancha con 3 campos opcionales — aditivo, no breakante.
- `PaymentLedger.id_account_receivable`: FK nullable sin `ondelete` — protegida por nullify (§5.3.2/6.2).
- Frontend: ningún consumidor actual referencia `accounts_receivable` por documento (no aplica cambio de contract más allá de campos nuevos en JSON).

### 8.5 Disponibilidad y operación

- El proceso es síncrono HTTP (sin jobs ni scheduler). Tiempo de subida dominado por lectura Excel (~1-2 s openpyxl para 276 filas).
- Recovery ante archivo malo: cualquier 400 deja la BD intacta (rollback). Recovery ante carga errónea ya confirmada con `force`: volver a subir el archivo correcto (corte vigente) — la guarda lo permite y C3 no reabre PAIDs (solo el reaparecer un documento los revive).

---

## 9. Reglas de Negocio (numeradas, trazables)

| ID | Regla | Fase | Fuente |
| :-- | :--- | :--- | :--- |
| BR-1 | Se descartan filas sin `Doc` (subtotales por cliente/sucursal) | A | borrador §3.1 |
| BR-2 | `document_number = Doc+Num` sin espacios, case-preserving; `Num` nulo ⇒ `Doc` | A | borrador §3.1 |
| BR-3 | Raíz de identificación = primera racha `\d+` del texto (descarta prefijo y dígito) | A | borrador §3.1 + D-4 |
| BR-4 | Resolución de cliente: `customers.document` → fallback `contacts.document` (asigna `contact.id_customer`, jamás `id_contact`); precedencia customer > contact | B | **D-4** |
| BR-5 | `id_invoice` por igualdad exacta de `document_number`; multi-cuota ⇒ `id_invoice` de menor `key`; sin hit ⇒ `NULL` | B | A-3 + borrador §3.2 |
| BR-6 | Aging = cascada sobre columnas del Excel (current → 1_to_30 → 31_to_60 → 61_to_90 → over_90); todo-cero ⇒ `NULL` | B | A-9 |
| BR-7 | En inserción: `paid_amount=0`, `status=OPEN`, `balance=total_amount`, `customer_document`+`identification_original`+`statement_date` poblados | D | borrador §3.4 + **D-1/D-3** |
| BR-8 | El corte es obligatorio y se parsea de la fila 2 (`DD/MM/YYYY`) | A | **D-3** |
| BR-9 | Guarda: corte nuevo < `MAX(statement_date)` almacenado ⇒ 400, salvo `force=true` | C1 | **D-3** |
| BR-10 | Cliente no resuelto ⇒ 400 con listado y **rollback total** | C1 | borrador §3.3 |
| BR-11 | Reemplazo: nullify FK `payment_ledger` + DELETE por `document_number IN (file)`, sin commit | C2 | borrador §3.3 + FK |
| BR-12 | Cierre: `OPEN ∧ doc ∉ file` ⇒ `PAID`, `paid_amount=balance_prev`, `balance=0`, conserva `aging_bucket`/`statement_date`; no toca PAID/PARTIAL | C3 | **D-2** |
| BR-13 | Documento PAID que reaparece ⇒ revive (BR-11 lo borra, D lo reinserta OPEN con datos nuevos) | C2/D | **D-2** |
| BR-14 | Transacción única all-or-nothing; commit exclusivamente en D; rollback en cualquier excepción | global | A-6/patrón |

---

## 10. Catálogo de Errores

| Código | Trigger | `detail` | Transacción |
| :--- | :--- | :--- | :--- |
| 400 | Extensión ≠ `.xlsx` | `"Only .xlsx files are supported"` | n/a (pre-parseo) |
| 400 | Corte no parseable (BR-8) | mensaje plano | rollback |
| 400 | Archivo vacío de detalle (A-10) | `"No valid detail rows found..."` | rollback |
| 400 | V1 clientes no resueltos (BR-10) | objeto estructurado §5.3.1 | rollback |
| 400 | V2 fechas inválidas (A-10) | `"N records have invalid dates"` | rollback |
| 400 | V3 corte anterior sin force (BR-9) | objeto estructurado §6.1.3 | rollback |
| 400 | V4 importes no numéricos | `"N records have non-numeric amounts"` | rollback |
| 404 | DELETE by-document sin coincidencias | patrón `Exceptions.register_not_found` | n/a |
| 401/403 | Sin JWT válido | estándar FastAPI | n/a |
| 500 | Cualquier otra excepción (Excel corrupto, error BD) | `"Error processing accounts receivable: {e}"` | rollback |

---

## 11. Criterios de Aceptación (verificables contra la muestra)

Cada AC ejecutable sobre BD dev (`docker compose -f docker-compose-dev.yaml up`, backend :8003) con `crm_backend/test/data/EstadoCuenta306090.xlsx`.

| AC | Criterio |
| :-- | :--- |
| **AC-1** (esquema) | Tras correr §4.3.1: las 3 columnas existen; `python -c "from app.models.budget import AccountReceivable"` sin error; GET `/budget/account-receivable/` responde 200 con los 3 campos nuevos (null en filas viejas). |
| **AC-2** (carga inicial) | `POST upload` ⇒ 200; `records_inserted == 121`; `rows_excluded_subtotals == 155`; `total_outstanding_balance == 439696679.72`; `unique_customers == 77`; `statement_date == "2026-08-26"`; `records_replaced == 0`; `records_closed == 0`. |
| **AC-3** (integridad filas) | En SQL: `SELECT count(*) FROM accounts_receivable WHERE source_file='EstadoCuenta306090.xlsx'` = 121; 0 filas con `id_customer IS NULL` o `customer_document IS NULL` o `identification_original IS NULL` o `statement_date IS NULL`; 56 filas con `total_amount < 0` (A-2); todos los `document_number LIKE 'rc%'` (51) tienen `id_invoice IS NULL`. |
| **AC-4** (idempotencia) | Recarga del mismo archivo ⇒ 200, `records_replaced == 121`, `records_closed == 0`, y el conteo total de la tabla + `SUM(balance)` quedan idénticos a AC-2/AC-3. |
| **AC-5** (legacy) | `legacy_debt_records >= 51` y coincide exactamente con `count(*) WHERE id_invoice IS NULL AND source_file = ...` (A-5). |
| **AC-6** (contact fallback) | Insertando un `contacts.document` con una raíz ausente de `customers` ⇒ la subida pasa, la fila apunta al `id_customer` del contacto, y `contact_fallback_resolved >= 1`; **no** se escribe ninguna columna `id_contact` en `accounts_receivable`. |
| **AC-7** (cierre D-2) | Copia del archivo sin 3 documentos OPEN (p. ej. quitar 3 filas `rc`) y con corte **posterior** (p. ej. 02/09/2026 editado en fila 2) ⇒ subida 200 con `records_closed == 3`; los 3 quedan `status='PAID'`, `balance=0`, `paid_amount==total_amount−0` (saldo previo), `statement_date` del corte en que se vieron vivos. |
| **AC-8** (guarda D-3) | Tras AC-7 (corte 02/09): subir el archivo original (corte 26/08) sin force ⇒ **400** con `file_cutoff=2026-08-26`/`stored_cutoff=2026-09-02` y BD sin cambios (mismo conteo/statuses que antes del intento); con `force=true` ⇒ 200, `"forced": true`. Corte igual ⇒ siempre 200. |
| **AC-9** (bloqueante clientes) | Archivo modificado con un `Identificacion` inexistente ⇒ 400 con la raíz en `missing_identifications`; `SELECT count(*)` demuestra que **no** se insertó ni borró ni cerró nada (rollback total). |
| **AC-10** (por-file duplicates) | `FVFE1595`: 2 filas tras la carga, ambos con el mismo `id_invoice` si existe en `invoices` (A-3). `NC559-...` idem. |
| **AC-11** (DELETE by-document) | `DELETE /budget/account-receivable/by-document/FVFE1595` ⇒ 200 `records_deleted==2`; documento inexistente ⇒ 404; con un `payment_ledger.id_account_receivable` apuntando a una fila eliminada ⇒ 200 sin `IntegrityError` y el ledger queda con FK a NULL. |
| **AC-12** (invariante) | Post-carga: `SELECT count(*) FROM accounts_receivable WHERE total_amount <> paid_amount + balance AND source_file=...` ⇒ 0 (invariante §4.5). |
| **AC-13** (regresión) | `budgetEngine` income: el `SUM(balance)` por año baja según lo cerrado; `npm run` no aplica; GETs de `account-receivable` y uploads de otros módulos siguen 200. |
| **AC-14** (auth) | POST/DELETE sin token ⇒ 401/403. |

---

## 12. Estrategia de Pruebas (el proyecto no tiene test suite)

1. **Smoke manual** con curl contra dev Docker:
   ```bash
   curl -X POST "http://127.0.0.1:8003/budget/upload/accounts-receivable" \
     -H "Authorization: Bearer $TOKEN" \
     -F "file=@crm_backend/test/data/EstadoCuenta306090.xlsx"
   curl -X DELETE "http://127.0.0.1:8003/budget/account-receivable/by-document/FVFE1595" \
     -H "Authorization: Bearer $TOKEN"
   ```
2. **Secuencia de ciclo de vida** (AC-2 → AC-4 → AC-7 → AC-8): mismo archivo, copia con 3 filas fuera + corte posterior, copia vieja forzada y no forzada.
3. **Matriz de validaciones** (§10): 1 archivo por 400 (extensión, sin corte, cliente fantasma, fecha basura).
4. **Verificación SQL post-cada-paso** (consultas en AC-3/AC-7/AC-12).
5. Recomendado (no bloqueante): fijar AC-2/AC-4/AC-7/AC-8 como script `crm_backend/test/etl_ar_smoke.py` idempotente contra BD dev limpia (`TRUNCATE accounts_receivable` previo con respaldo de datos de prueba).

---

## 13. Supuestos y Dependencias

- **Dep-BD**: `psycopg2` + Postgres 16 con esquema `budget` accesible; los 3 `ALTER` de §4.3.1 aplicados **antes** de desplegar el código (orden: ALTER → deploy; el código nuevo sin ALTER ⇒ 500 `UndefinedColumn` con rollback limpio).
- **Datos**: `customers.document`/`contacts.document` son `Float unique not null`; asunción comercial confirmada: las raíces del Excel vienen **sin** dígito de verificación y coinciden con el documento con el que se facturó; un cambio de documento del cliente se modela en CRM como contacto con el documento alterno.
- **Datos**: `invoices.invoice_number` sigue la convención `FVFE####` (normalización del ETL de costos); no se intentan variantes alternativas (a diferencia del imputador probabilístico de payment-ledger).
- **Archivo**: SIIGO mantiene header en fila 4 y subtotales sin `Doc`. Si cambia el layout (columnas renombradas, acentos fuera), el ETL falla **ruidosamente** (KeyError ⇒ 500 con rollback), nunca silencia.
- **Operación**: el upload es manual por un usuario autenticado con conocimiento del corte vigente; no hay scheduler.
- **El `42` de `legacy_debt_records` y el `50` de `records_replaced` en el borrador** se declararon ilustrativos y quedaron reemplazados por fórmulas exactas (§6.1.1).

---

## 14. Matriz de Trazabilidad (borrador → especificación final)

| Sección del borrador | Estado | Dónde |
| :--- | :--- | :--- |
| §1 Objetivo | Aceptado + snapshot sync | §1, D-2 |
| §2.1/2.2 Estructura entrada | Verificado + columna Unicode exacta + fila 2 corte | §4.1, §4.2 |
| §3.1 Fase A | Aceptado + parseo corte + contadores | §5.1, BR-1..3 |
| §3.2 Fase B (customers) | **Corregido**: campo real `document` (Float), fallback contacts | §5.2.1-2, BR-4, D-4 |
| §3.2 Fase B (invoices + aging) | Aceptado + regla min-key multi-cuota | §5.2.3-4, BR-5/6, A-3 |
| §3.3 Fase C | Aceptado + guarda D-3 + nullify FK + cierre D-2 | §5.3, BR-9..12 |
| §3.4 Fase D | Aceptado + 3 campos nuevos | §5.4, §4.5, BR-7 |
| §4 "No migraciones" | **ANULADO** por D-1/D-3 | §4.3 + §0 aviso |
| §5.1 POST upload | Ampliado (`force`, `statement_date`, `records_closed`, `forced`, details nuevos) | §6.1 |
| §5.2 DELETE by-document | Ruta corregida (singular) + FK nullify | §6.2, D-5/FK |
| (nuevo) Ciclo de vida | Especificado con máquina de estados | §5.5 |
| (nuevo) Reglas de negocio | BR-1..BR-14 | §9 |
| (nuevo) Aceptación | AC-1..AC-14 | §11 |

---

## 15. Checklist de Implementación (orden recomendado)

1. [ ] `ALTER TABLE` §4.3.1 en dev y prod **antes** del deploy.
2. [ ] Modelo: +3 columnas (§4.3.2).
3. [ ] Schema Pydantic: +3 campos, quitar `ge=0`, default `status="OPEN"` (§4.4).
4. [ ] CRUD: 4 funciones (§7).
5. [ ] `BudgetTemplates`: eliminar `process_estado_cuenta`, agregar contadores + 5 métodos + helpers de corte (§5).
6. [ ] `upload.py`: endpoint con orquestación §6.1 (guardar `seek(0)` tras parseo de corte).
7. [ ] `accountReceivable.py` API: ruta §6.2.
8. [ ] Pasos §12.1–12.4 + SQL de AC-3/AC-12 ⇒ cerrar AC-1..AC-14.

---

*Fin de la especificación — v1.0 consolidada el 2026-09-01 a partir del borrador del stakeholder, el análisis del código fuente del repositorio, los datos del archivo de muestra (verificación cuantitativa: 276 crudas − 155 subtotales = 121 detalle = 119 documentos distintos; saldo 439,696,679.72; 77 clientes; 51 rc; 56 negativos) y las decisiones D-1..D-5 de la sesión interactiva.*
