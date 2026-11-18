# Especificación Técnica: ETL payment-ledger (Extractos de Liquidez)

> **Origen**: Historias de usuario de Recibos.xlsx + ciclo de preguntas resuelto (4/4).
> **Módulo**: budget → tabla `payment_ledger`.
> **Patrón de referencia**: `backend.02_06_Spec_Backend_budgets_actual_expenses.md` (4 fases ETL transaccionales).

## 1. Objetivo del Proceso

Establecer la tubería ETL para procesar el archivo Recibos.xlsx (export del auxiliary de cartera/proveedores del sistema contable SIIGO) y poblar la tabla `payment_ledger` como **ledger único de movimientos de liquidez y ajustes**, clasificando cada transacción con `transaction_nature` para que el motor financiero consuma correctamente:

- **CASH** (RC/CE): se usa para graficar el Flujo de Caja en los bancos.
- **NON_CASH_ADJUSTMENT** (NC/NO/DMC y SI opcionales): se ignora para bancos, pero se suma para determinar que la factura del cliente/proveedor ya fue saldada.

## 1.1 Tablero de Decisiones (trazabilidad de supuestos)

| # | Decisión | Origen |
|---|----------|--------|
| D1 | Ingerir RC, CE, NC, NO, DMC (ya no solo RC/CE) | Regla del usuario (naturaleza de transacción) |
| D2 | `SI` (saldo inicial) excluido por defecto; included con parámetro `include_initial_balances=true` | Usuario (Q2 + ajuste) |
| D3 | FV/FC siempre excluidos (viven en módulos de facturas) | Usuario (Q2, opción 1) |
| D4 | Dirección de caja derivada del signo invertido: `amount = Movimiento × -1`; `>0` → `in`, `<0` → `out`. El prefijo solo define naturaleza, no dirección | Usuario (Q1, opción 2) |
| D5 | Inversión × -1 aplica a TODAS las filas, también NON_CASH; `cash_flow` solo se puebla en CASH (NULL en NON_CASH) | Usuario (Q3, opción 1) |
| D6 | Imputación: extracción anclada a marcador de documento + validación contra `invoices`; solo se vincula si existe exactamente una factura; cero o múltiples candidates válidos siguen reglas de precedencia (Fase B) | Usuario (Q4, opción 2) |
| D7 | Salvaguarda anti-falsos-positivos: un número solo es candidato si sigue inmediatamente a un marcador (`VENTA`, `FV`, `FE`, `DSC`, `DMC`, `NC`). Los años (ENERO 2026) nunca son candidatos | Usuario (Q4, nota) |
| D8 | `accounting_account` ← `Cuenta` (solo el código antes del primer espacio, patrón actual_expenses); `description` ← `Concepto` (texto completo) | Usuario (regla 12) |
| D9 | `Tipo de Cuenta` es solo contexto de sección del auxiliar (hay 94/197 filas CASH contradictorias); nunca determina dirección | Supuesto 2 explicado y aceptado vía Q1 |
| D10 | Reemplazo atómico por `receipt_number` (no por source_file, porque el nombre "Recibos.xlsx" se repite entre cargas mensuales) | Adaptación del patrón 02_06 |
| D11 | Terceros: `third_party` texto libre; vinculación opcional no-bloqueante a `customers`/`accounts_receivable` | Supuestos 3 y 5 aceptados |
| D12 | `receipt_number` se almacena **solo alfanumérico**, sin espacios ni caracteres especiales (`"RC  - 3017"` → `"RC3017"`). El prefijo de clasificación se deriva del primer token **antes** del recorte. El schema fuerza `^[0-9A-Za-z]+$` | Decisión posterior del usuario |

## 2. Estructura de Datos de Entrada

### 2.1 Archivo Fuente
- **Nombre del archivo**: Recibos.xlsx (validado con `test/data/Recibos.xlsx`)
- **Formato**: Excel (.xlsx), engine openpyxl
- **Hoja**: primera hoja (`sheet_name=0`; en el export es `ExportarAExcel`)
- **Header**: Fila 1 (`header=0`, valor por defecto de pandas)
- **Volumen de referencia**: 1,418 filas × 11 columnas

### 2.2 Columnas del Excel (verbatim del export)
| Columna | Tipo pandas | Uso en ETL |
|---------|-------------|------------|
| Nombres | object (disperso) | `ffill` → `third_party` |
| Sucursal_ | object (vacía) | Ignorada |
| Empresa | object (disperso) | `ffill` → contexto (no se persiste) |
| Tipo de Cuenta | object (disperso) | `ffill` → contexto (no determina dirección, D9) |
| Abona A | object | Ignorada (referencia al documento del auxiliar) |
| Fecha | datetime64[ns] | `payment_date` |
| IdCuentaContableDocumento | object | `receipt_number` + prefijo → naturaleza |
| Cuenta | object | `accounting_account` (código antes del 1er espacio) |
| Concepto | object | `description` + extracción de documento afectado |
| Movimiento | float64 | `payment_amount` (× -1) |
| Saldos | float64 | **Ignorada** |

### 2.3 Prefijos de documento presentes en el export (recuento real)
| Prefijo | Filas | Naturaleza | Default |
|---------|-------|------------|---------|
| RC (Recibo de Caja) | 112 | CASH | Se ingiere |
| CE (Comprobante de Egreso) | 85 | CASH | Se ingiere |
| NC (Nota de Crédito) | 170 | NON_CASH_ADJUSTMENT | Se ingiere |
| NO (Comprobante de nómina/ajuste) | 46 | NON_CASH_ADJUSTMENT | Se ingiere |
| DMC (Nota débito) | 6 | NON_CASH_ADJUSTMENT | Se ingiere |
| SI (Saldo Inicial) | 20 | NON_CASH_ADJUSTMENT | **Excluido** (incluible con flag) |
| FV / FC (Facturas) | 296 | — | Siempre excluidas |
| (vacío / filas Total) | 644 | — | Excluidas naturalmente |

## 3. Flujo de Ejecución (Execution Pipeline)

Una sola transacción por upload, con las 4 fases del patrón del módulo (`process → map → validate → dedupe → bulk_insert`), como métodos de `BudgetTemplates`.

### 3.1 Fase A: Limpieza de Datos (Data Cleansing)

**Método**: `BudgetTemplates.process_payment_ledger(include_initial_balances: bool = False) -> DataFrame`

1. **Cargar Excel**: `pd.read_excel(self.file, engine="openpyxl", sheet_name=0)`; guardar `self.total_rows_raw = len(df)`.
2. **Aplanamiento de jerarquías**: `ffill()` sobre `Nombres`, `Empresa`, `Tipo de Cuenta` para que toda fila de detalle tenga el contexto del tercero.
3. **Normalizar recibo**: `IdCuentaContableDocumento.astype(str).str.strip()` colapsando espacios internos múltiples (`\s+` → `' '`); el prefijo se toma del primer token de esa forma; luego se eliminan todos los caracteres no alfanuméricos para el valor almacenado (D12). Ej: `"RC  - 3017"` → prefijo `RC` → `receipt_number = "RC3017"`.
4. **Prefijo** = primer token de `receipt_number`. Filas con documento vacío/`nan` (subtotales "Total Cuentas por Cobrar", "Total CAPRATEX S.A.S.", "Total <Cliente>") quedan excluidas automáticamente por no matchear ningún prefijo.
5. **Filtro de naturaleza**: conservar prefijos en `{RC, CE}` → `transaction_nature="CASH"`; `{NC, NO, DMC}` → `"NON_CASH_ADJUSTMENT"`; `{SI}` solo si `include_initial_balances=True` (como `NON_CASH_ADJUSTMENT`). FV/FC/otros: excluidos.
6. **Signo de flujo de caja (D4/D5)**: `payment_amount = Movimiento × -1` para **todas** las filas conservadas.
7. **Dirección (solo CASH)**: `cash_flow = "in"` si `payment_amount > 0`; `"out"` si `< 0`; filas CASH con monto exactamente 0 → `cash_flow=NULL` (se conservan, no se dan en el archivo actual). En NON_CASH: `cash_flow = NULL` siempre.
8. **Campos de salida**:
   - `payment_date = pd.to_datetime(Fecha, errors="coerce").dt.date`
   - `accounting_account = Cuenta` partida en el primer espacio: token inicial (ej `"13050501 deudores nacionales"` → `"13050501"`)
   - `description = Concepto` (texto original completo)
   - `third_party = Nombres`
9. **Descartes**: filas conservadas cuyo `Movimiento` o `Fecha` sea nulo → se excluyen y se cuentan en `rows_skipped_null`.

**Resultado esperado con el archivo de ejemplo**: 419 filas (197 CASH + 222 NON_CASH); 439 con `include_initial_balances=True`.

### 3.2 Fase B: Mapeo Relacional (Imputación del Documento Afectado)

**Método**: `BudgetTemplates._map_payment_ledger_relational_data(db: Session) -> DataFrame`

**a) Extracción de candidatos (`affected_doc_number`)** — anclada a marcador (D6/D7). Sobre `description` en mayúsculas, aplicar patrones **en este orden de precedencia**:

| Prioridad | Regex | Ejemplo de Concepto | Candidato |
|-----------|-------|---------------------|-----------|
| 1 | `VENTA\s+(\d{3,7})` | `PAGO FACTURA DE VENTA 1461` | 1461 |
| 2 | `\bFV\s+(\d{3,7})` | `PAGO DEV DCTO FV 1359 558` | 1359 (no 558 ✓) |
| 3 | `\bFE\s+(\d{3,7})` | `PAGO FEET1164// ALARMAS FEBRERO 2026 1164 FE 2512` | 2512 (86/2026 no✓) |
| 4 | `\bDSC\s+(\d{3,7})` | `PAGO 2026146// HONORARIOS ENERO 2026 2026146 DSC 689` | 689 |
| 5 | `\bDMC\s+(\d{3,7})` | `DEV DMC 380` | 380 |
| 6 | `\bNC\s+(\d{3,7})` | `ELIMINADO CON DOCUMENTOS DE AJUSTE NO RM` | — |

Reglas: un número es candidato **solo** si sigue inmediatamente (separado por espacios) al marcador; se permiten múltiples candidatos por fila deduplicados por orden de aparición; meses/años sin marcador adyacente jamas son candidatos (`NOMINA FEBRERO 2026` → cero candidatos ✓).

**b) Validación contra `invoices`** (la BD es el juez): para cada candidato `n` en orden de precedencia, buscar en `Invoice.invoice_number` las formas normalizadas `{str(n), "FVFE" + str(n)}` (patrón `_clean_document` del ETL de costos).
- Si el candidato coincide con **exactamente un** `invoice_number` pero el export permite múltiples filas por cuotas (`key` 1..n del `UniqueConstraint('invoice_number','key')`): vincular la fila con el **menor `key`** (registro maestro de la factura).
- El **primer candidato** (orden de tabla) que resuelva a factura existente → `id_invoice`.
- Ningún candidato resuelve (NC, DSC, nómina, anticipos, referencias no-CRM) → `id_invoice = NULL` y **la fila NO se descarta**. Se contabiliza en `documents_not_imputed`.

**c) Vinculación opcional no-bloqueante (D11)**:
- `id_customer`: para filas RC, normalizar `third_party` (upper, trim) y buscar coincidencia exacta con `Customer.name`; si no hay → NULL. Nunca bloquea.
- `id_account_receivable`: NULL en el ETL (queda para la mano del usuario/API CRUD; el ETL de `accounts_receivable` es un stub aparte).

**Mapeo total Excel → BD**:

| Campo Excel | Campo BD | Transformación |
|-------------|----------|----------------|
| IdCuentaContableDocumento | receipt_number | strip + colapso de espacios + remoción de no-alfanuméricos (D12) |
| IdCuentaContableDocumento (prefijo) | transaction_nature | RC/CE→CASH; NC/NO/DMC/SI→NON_CASH_ADJUSTMENT |
| Movimiento × -1 | payment_amount | Firmado (+ = entrada, − = salida) |
| signo de payment_amount (solo CASH) | cash_flow | in / out / NULL |
| Fecha | payment_date | DATE |
| Cuenta | accounting_account | código antes del 1er espacio |
| Concepto | description | texto íntegro |
| Concepto | id_invoice | Fase B (regex + validación en BD) |
| Nombres | third_party | texto libre |
| Nombres | id_customer | match exacto opcional (solo RC) |

### 3.3 Fase C: Validaciones y Reemplazo (Safety & Upsert)

**Método**: `BudgetTemplates._validate_payment_ledger_integrity(db: Session) -> None`
1. `receipt_number` vacío/NaN en alguna fila restante → HTTP 400, rechazo total.
2. Fechas inválidas (`payment_date` NaN) → HTTP 400: "N records have invalid dates".
3. `Movimiento` no numérico → HTTP 400, rechazo total.
4. Validaciones NO-bloqueantes (se reportan, no fallan): candidatos sin factura, `third_party` sin cliente.

**Método**: `BudgetTemplates._handle_payment_ledger_duplicates(db: Session) -> int`
- **Reemplazo atómico por recibo (D10)**: antes de insertar, eliminar los registros existentes cuyos `receipt_number` estén entre los del archivo (DELETE dentro de la misma transacción, **sin commit** — el caller controla, igual que `_handle_actual_expense_duplicates`). Re-subir Recibos.xlsx actualizado refresca exactamente los recibos impactados sin borrar historial de otros periodos.
- Duplicados internos del mismo archivo: verificado 0 con la clave natural completa `(receipt_number, third_party, payment_date, accounting_account, description, amount)`; no se agrega UNIQUE en BD porque el mismo recibo paga múltiples facturas con montos iguales (5 casos de colisión parcial en el ejemplo legítimo: CE-6649 FEET1164/1991 $102,283).

### 3.4 Fase D: Inserción Masiva (Bulk Insert)

**Método**: `BudgetTemplates._bulk_insert_payment_ledger(db: Session, source_filename: str) -> list`
1. Convertir filas a `PaymentLedgerCreate`.
2. `crud.create_payment_ledger_bulk(db, records)` (ya existe en `app/crud/budget/paymentLedger.py`, línea 25).
3. Cualquier error → `db.rollback()` (revierte delete + insert).

## 4. Estructura de la Tabla payment_ledger

### 4.1 Campos Existentes
| Campo | Cambio |
|-------|--------|
| id_payment_ledger PK | se mantiene |
| id_account_receivable | **pasa a NULLABLE** (CE/NC/NO no tienen cartera) |
| payment_date NOT NULL | se mantiene |
| payment_amount Float | **pasa a `Numeric(15, 2)` firmado** (precisión contable, patrón 02_06) |
| payment_method | se mantiene (NULL en este ETL; no hay columna fuente) |
| reference_number | se mantiene (legacy de RecibosDePago.xlsx) |
| id_invoice (FK nullable) | se mantiene — imputación Fase B |
| source_file, created_at | se mantienen |

### 4.2 Campos Nuevos
| Campo | Tipo | Nullable | Descripción |
|-------|------|----------|-------------|
| receipt_number | String(60) | No (índice) | Recibo limpio: "RC3017", "NC558" (solo alfanumérico, D12) |
| transaction_nature | String(25) | No | `CASH` \| `NON_CASH_ADJUSTMENT` (CHECK) |
| cash_flow | String(8) | Sí | `in` \| `out` \| NULL solo en NON_CASH (CHECK) |
| accounting_account | String(20) | No | Ej "13050501" (como actual_expenses) |
| description | Text | Sí | `Concepto` completo |
| third_party | String(200) | Sí | Cliente o proveedor (texto libre) |
| id_customer | FK customers.id_customer | Sí | Vinculación RC opcional |

### 4.3 Migración SQL (manual — proyecto sin Alembic; `create_all` no altera tablas existentes)

```sql
ALTER TABLE payment_ledger
    ADD COLUMN receipt_number VARCHAR(60),
    ADD COLUMN transaction_nature VARCHAR(25) NOT NULL DEFAULT 'CASH',
    ADD COLUMN cash_flow VARCHAR(8),
    ADD COLUMN accounting_account VARCHAR(20) NOT NULL DEFAULT '',
    ADD COLUMN description TEXT,
    ADD COLUMN third_party VARCHAR(200),
    ADD COLUMN id_customer INTEGER REFERENCES customers(id_customer);

ALTER TABLE payment_ledger
    ALTER COLUMN id_account_receivable DROP NOT NULL,
    ALTER COLUMN payment_amount TYPE NUMERIC(15,2);

CREATE INDEX IF NOT EXISTS ix_payment_ledger_receipt_number
    ON payment_ledger (receipt_number);

ALTER TABLE payment_ledger
    ADD CONSTRAINT ck_payment_ledger_nature
        CHECK (transaction_nature IN ('CASH','NON_CASH_ADJUSTMENT')),
    ADD CONSTRAINT ck_payment_ledger_flow
        CHECK (cash_flow IS NULL OR cash_flow IN ('in','out'));
```

> Si la tabla puede vaciarse (el stub actual nunca insertó datos vía upload), es válido `DROP TABLE payment_ledger` y dejar que `create_all` la regenere con el modelo nuevo. Verificar primero: `SELECT count(*) FROM payment_ledger;`

## 5. Endpoints

### 5.1 POST /budget/upload/payment-ledger (stub existente → implementar)

**Archivo**: `app/api/budget/upload.py` (líneas 169-180, actualmente TODO).

**Request** (multipart/form-data):
- `file`: Recibos.xlsx (obligatorio, solo .xlsx)
- `include_initial_balances`: bool Form, **default `false`** (D2)
- Auth: JWT Bearer (`get_current_user`)

**Response 200** (valores esperados para el archivo de ejemplo, imputación dependiente del estado de `invoices`):
```json
{
  "message": "Payment ledger uploaded successfully",
  "records_inserted": 419,
  "records_replaced": 0,
  "source_file": "Recibos.xlsx",
  "include_initial_balances": false,
  "details": {
    "total_rows_processed": 1418,
    "rows_excluded_totals": 644,
    "rows_excluded_documents": 296,
    "rows_excluded_initial_balances": 20,
    "rows_skipped_null": 0,
    "cash_records": 197,
    "non_cash_records": 222,
    "cash_in_count": 116,
    "cash_out_count": 81,
    "total_cash_in": 508861452.00,
    "total_cash_out": -367856681.92,
    "net_liquidity": 141004770.08,
    "total_non_cash_adjustments": 379589107.24,
    "rows_with_document_candidate": 79,
    "invoices_imputed": 0,
    "documents_not_imputed": 79
  }
}
```

**Response 400**: validaciones de Fase C con detalle (igual patrón actual-expenses).

**Lógica del endpoint**:
```python
@router.post("/payment-ledger")
async def upload_payment_ledger(
    file: UploadFile = File(...),
    include_initial_balances: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload and process Recibos.xlsx for the payment ledger (cash-flow ETL)."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .xlsx files are supported",
        )
    file_content = await file.read()
    file_bytes = BytesIO(file_content)
    try:
        etl = BudgetTemplates(file_bytes)
        df = etl.process_payment_ledger(include_initial_balances=include_initial_balances)
        etl._map_payment_ledger_relational_data(db)
        etl._validate_payment_ledger_integrity(db)
        records_deleted = etl._handle_payment_ledger_duplicates(db)
        inserted = etl._bulk_insert_payment_ledger(db, file.filename)
        return { ...ver estructura Response... }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing payment ledger: {str(e)}",
        )
```

### 5.2 GET /budget/payment-ledger (extensión de filtros — motor financiero)

Agregar query params opcionales al endpoint de lista existente (`app/api/budget/paymentLedger.py`) y a `crud.get_payment_ledger`: `transaction_nature`, `cash_flow`, `receipt_number`, `third_party`, `date_from`, `date_to`. El motor de flujo de caja consulta `?transaction_nature=CASH` (+ cash_flow in/out); la conciliación de saldos de factura suma `CASH` + `NON_CASH_ADJUSTMENT` agrupando por `id_invoice`.

## 6. Archivos a Modificar (Backend)

> Todos los archivos ya existen (el módulo paymentLedger fue creado para RecibosDePago.xlsx). No se crean archivos nuevos, no hay cambios de registro en `__init__`.

| # | Archivo | Acción |
|---|---------|--------|
| 1 | `app/models/budget/paymentLedger.py` | MODIFICAR: +7 columnas; `id_account_receivable` nullable; `payment_amount` → `Numeric(15,2)`; CHECKs; índice receipt_number |
| 2 | `app/schemas/budget/paymentLedger.py` | MODIFICAR: nuevos campos; **eliminar `ge=0` de `payment_amount`** (ahora firmado); `id_account_receivable` Optional; patterns para enums |
| 3 | `app/crud/budget/paymentLedger.py` | MODIFICAR: `delete_payment_ledger_by_receipts(db, receipt_numbers) -> int` (sin commit); filtros nuevos en `get_payment_ledger` |
| 4 | `app/api/budget/upload.py` | MODIFICAR: implementar stub líneas 169-180 (5.1) |
| 5 | `app/api/budget/paymentLedger.py` | MODIFICAR: nuevos query params en GET lista |
| 6 | `app/utils/templates/budgetTemplates.py` | MODIFICAR: reemplazar `process_recibos_de_pago()` stub + agregar `_map/_validate/_handle_duplicates/_bulk_insert` del ledger + constantes de patrones |

### 6.1 Modelo resultante

```python
class PaymentLedger(Base):
    """Cash-flow and adjustment ledger. Ingested from Recibos.xlsx (SIIGO auxiliares)."""
    __tablename__ = "payment_ledger"

    id_payment_ledger = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(60), nullable=False, index=True)
    transaction_nature = Column(
        String(25), nullable=False, server_default="CASH",
        CheckConstraint("transaction_nature IN ('CASH','NON_CASH_ADJUSTMENT')"),
    )
    cash_flow = Column(
        String(8),
        CheckConstraint("cash_flow IS NULL OR cash_flow IN ('in','out')"),
    )
    payment_date = Column(Date, nullable=False)
    payment_amount = Column(Numeric(15, 2), nullable=False, server_default="0")
    accounting_account = Column(String(20), nullable=False, server_default="")
    description = Column(Text)
    third_party = Column(String(200))
    id_account_receivable = Column(
        Integer, ForeignKey("accounts_receivable.id_account_receivable"), nullable=True
    )
    id_customer = Column(Integer, ForeignKey("customers.id_customer"))
    id_invoice = Column(Integer, ForeignKey("invoices.id_invoice"))
    payment_method = Column(String(40))
    reference_number = Column(String(60))
    source_file = Column(String(200))
    created_at = Column(DateTime, server_default=func.now())

    account_receivable = relationship("AccountReceivable", back_populates="payments")
    customer = relationship("Customer")
    invoice = relationship("Invoice", backref="payment_ledger")
```

### 6.2 Esquemas resultantes

```python
class PaymentLedgerBase(BaseModel):
    receipt_number: str = Field(..., max_length=60, pattern="^[0-9A-Za-z]+$", description="Cleaned receipt number, e.g. 'RC3017'")
    transaction_nature: str = Field(..., pattern="^(CASH|NON_CASH_ADJUSTMENT)$")
    cash_flow: Optional[str] = Field(None, pattern="^(in|out)$", description="Direction; only for CASH rows")
    payment_date: date = Field(..., description="Exact collection/payment date")
    payment_amount: float = Field(..., description="Signed bank-view amount: positive inflow, negative outflow")
    accounting_account: str = Field(..., max_length=20)
    description: Optional[str] = Field(None, description="Full Concepto text from Excel")
    third_party: Optional[str] = Field(None, max_length=200)
    id_account_receivable: Optional[int] = Field(None, gt=0)
    id_customer: Optional[int] = Field(None, gt=0)
    id_invoice: Optional[int] = Field(None, gt=0, description="Affected invoice imputed from Concepto")
    payment_method: Optional[str] = Field(None, max_length=40)
    reference_number: Optional[str] = Field(None, max_length=60)
    source_file: Optional[str] = Field(None, max_length=200)
```

### 6.3 CRUD adicional

```python
def delete_payment_ledger_by_receipts(db: Session, receipt_numbers: List[str]) -> int:
    """Delete ledger rows by receipt_number list (atomic replace). No commit here."""
    count = db.query(PaymentLedgerModel).filter(
        PaymentLedgerModel.receipt_number.in_(receipt_numbers)
    ).delete(synchronize_session=False)
    return count
```

### 6.4 Constantes ETL (en `BudgetTemplates`)

```python
CASH_PREFIXES = {"RC", "CE"}
NON_CASH_PREFIXES = {"NC", "NO", "DMC"}
INITIAL_BALANCE_PREFIXES = {"SI"}
DOC_CANDIDATE_PATTERNS = [
    r"VENTA\s+(\d{3,7})",
    r"\bFV\s+(\d{3,7})",
    r"\bFE\s+(\d{3,7})",
    r"\bDSC\s+(\d{3,7})",
    r"\bDMC\s+(\d{3,7})",
    r"\bNC\s+(\d{3,7})",
]
```

## 7. Criterios de Aceptación (verificables contra `test/data/Recibos.xlsx`)

### 7.1 Funcionales
- [ ] Upload del ejemplo inserta **419 filas** (197 `CASH` + 222 `NON_CASH_ADJUSTMENT`); con `include_initial_balances=true` inserta **439**
- [ ] Cuentas `FV`/`FC` (296) y filas `Total` (644) nunca se insertan
- [ ] `rc` `"RC  - 3017"` queda como `"RC3017"` (D12: sin espacios ni especiales)
- [ ] Fila `"PAGO FACTURA DE VENTA 1461"` (Mov −22,613,890) → `payment_amount=+22613890.00`, `CASH`, `cash_flow='in'`, `id_invoice` apuntando a `FVFE1461` si existe
- [ ] Fila RETEFTE BANCOLOMBIA `RC - 2423` (Mov +31,006.80) → `payment_amount=−31006.80`, `CASH`, `cash_flow='out'` **a pesar del prefijo RC** (regla D4/anti-excepciones)
- [ ] Fila `CE - 6579` ANTICIPO WADY MASTER bajo sección "Cuentas por Cobrar" → salida (`−1,300,000`, `cash_flow='out'`) — el prefijo/signo mandan sobre `Tipo de Cuenta` (94 casos así)
- [ ] NC `"DEV DCTO FV 1359"` → `NON_CASH`, `cash_flow NULL`, candidato 1359; el "558" posterior **no** se toma
- [ ] `"NOMINA FEBRERO 2026"` (NO −3,956,000) → `payment_amount=+3,956,000`, `NON_CASH`, **cero candidatos** (2026 no se imputa aunque mañana exista una factura 2026: nunca es candidato porque no hay marcador)
- [ ] `accounting_account` = código. Ej `"21050601 bancolombia rotativo"` → `"21050601"`; `description` = Concepto íntegro
- [ ] Totales de control cuadran: `total_cash_in=508,861,452.00`, `total_cash_out=−367,856,681.92`, `net_liquidity=141,004,770.08`
- [ ] Filas sin factura coincidente se insertan con `id_invoice=NULL` y engrosan `documents_not_imputed`

### 7.2 De integridad
- [ ] Upload repetido del mismo archivo: `records_replaced == records_inserted` y conteo final idéntico (idempotencia por recibo, D10)
- [ ] Re-upload de una versión corregida de Recibos.xlsx solo reemplaza los recibos presentes en el archivo nuevo
- [ ] Error en cualquier fase → rollback total (ni delete ni insert visibles)
- [ ] `payment_amount` admite negativos (schema sin `ge=0`) sin romper la API CRUD manual de `PaymentLedgerCreate`

### 7.3 De rendimiento
- [ ] 1,418 filas procesadas e insertadas en < 10 s; bulk sin límite de batch
- [ ] Una sola lectura del Excel (Fase A); validación de facturas en consultas batch `IN(...)` (no por fila)

### 7.4 De seguridad
- [ ] JWT requerido; solo `.xlsx`; errores sin stack trace (detail controlado)

## 8. Dependencias y Consideraciones

### 8.1 Conocidas/Anomalías del dato fuente (registradas, no corregidas por diseño)
- **RC positivos** (5): RETEFTE/IMPUESTOS Bancolombia. Con D4 se guardan como salida — coherente con el banco.
- **CE negativos** (9): anticipos/préstamos de empleados. Con D4 se guardan como entrada (devoluciones percibidas) — coherente con el banco.
- **Prefijo vs Tipo de Cuenta contradictorio**: 94/197 CASH. D9 documenta por qué se ignora el contexto.
- **NC con signo mixto** (83 neg/86 pos): se preserva la semántica de deuda invertida (D5).
- `reference_number`/`payment_method` quedan NULL (el export no trae método de pago).
- **Riesgo**: si el export cambia de formato (columnas), el ETL falla ruidosamente en Fase A (HTTP 500 con detalle) → no silenciar KeyError.

### 8.2 Librerías: pandas, openpyxl, sqlalchemy, fastapi, python-multipart — todas ya en requirements.txt.

### 8.3 Orden de implementación sugerido
1. Verificar si `payment_ledger` tiene datos → ALTER (4.3) o DROP+create_all.
2. Modelo (6.1) → 3. Schema (6.2, quitar `ge=0`) → 4. CRUD (6.3 + filtros lista) → 5. Métodos ETL en `BudgetTemplates` (3.1-3.4, 6.4) → 6. Endpoint upload (5.1) → 7. Query params GET (5.2) → 8. Prueba con `test/data/Recibos.xlsx` validando §7.1.

### 8.4 Out of scope
- Actualización de `paid_amount`/saldos en `invoices` o `accounts_receivable` (solo se almacena el FK `id_invoice`; la imputación efectiva la consumen reportes).
- Vinculación de CE/NC a proveedores (no existe tabla vendors).
- Parsing del `Saldos` acumulado y validación de pólizas contables (debe cuadrar = 0 por cliente/empresa).
