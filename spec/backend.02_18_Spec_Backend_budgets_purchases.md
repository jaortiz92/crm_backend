# Spec Backend: Plan de Importaciones (líneas de compra) + cuotas a proveedores + arrastre purchase

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S8-BUDGET-PURCHASES` |
| **Espec counterparts** | FE: `frontend.03_12` (FE-S9-PURCHASES-BODEGA). Bases: BE-S4 (`02_12`), BE-S4D (`02_13`), BE-S6 (`02_16`), BE-S7 (`02_17`) |
| **Tablas nuevas** | **CERO.** Las compras son filas de `budget_lines` con un tercer valor de enum |
| **DDL requerido** | 1 ALTER manual de enum (ver §3.3 — el único cambio de esquema; `create_all` jamás agrega valores a un tipo existente) |
| **Convenciones** | T-03 legacy `db.query`, T-05 un solo commit, camelCase filenames, checklist de 4 puntos de registro (aquí: no hay entidad nueva, solo extensión) |

---

## 1. Problema y modelo conceptual

La organización importa mercancía y paga al proveedor **por lo importado**, no por lo vendido. Hoy el único costo del escenario se deriva de los ingresos (`ingreso × cogs_pct`, términos desde `budget_date` del ingreso — FE-S7), lo cual sub-registra la salida de caja cuando queda inventario en bodega.

```
COMPRA (fila material budget_lines line_type=purchase)
  ├─ cuota_i = monto × payment_pct   (line_payable_terms de la Línea del CECO)
  ├─ fecha_i = budget_date (fecha de importación) + payment_days_i
  └─ si el CECO no tiene términos ⇒ cuota única 100 % en la fecha de importación (regla D-S7-4)
P&L / Ejecutiva: intocados (costo de ventas sigue = ingreso × cogs_pct por causación)
Bodega (derivación pura del FE): Σ compras − Σ costo de ventas causado, acumulado mensual
```

**Regla de fuente única (D-4, VINCULANTE):** un CECO con ≥1 línea de compra en el escenario es **"comprador"**. El pago a proveedores (caja) de un CECO comprador se deriva de sus **compras**; el de un CECO no comprador sigue derivándose del ingreso (FE-S7 vigente). Nunca ambas fuentes para el mismo CECO ⇒ cero doble-cuenta. El P&L no conoce esta regla (no cambia).

## 2. Alcance

**Incluye:** (1) valor de enum `purchase` + migración; (2) semántica de fila compra; (3) guards en el line manager (create/update); (4) ingesta opcional de compras como TERCER archivo del upload del planning con plantilla propia simple; (5) arrastre de cuotas de compra N−1→N (origen `"purchase"`) con la MISMA regla de fuente única aplicada sobre el escenario fuente; (6) resultados de upload con claves aditivas.
**Excluye (v1):** motor analítico Pilar 2 (`get_cash_flow`/`project_cash_flow`/`get_pnl` intocados — R-BE-1 documentada), comparación compra presupuestada vs. `payable_ledger` real, saldo inicial de bodega por arrastre (PQ-BE-1), descarga auto-generada de la plantilla (PQ-BE-2), columna "total compras" en el dashboard (`get_planning_scenarios` intocada).

## 3. Modelo de datos

### 3.1 `LineTypeEnum` (modelo Y schemas — ambos archivos definen el enum)

`app/models/budget/budgetLine.py` y `app/schemas/budget/budgetLine.py`:

```python
class LineTypeEnum(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"
    PURCHASE = "purchase"
```

**Hecho verificado en la BD dev:** el tipo Postgres `linetypeenum` almacena los **NAMES** de los miembros (`'INCOME'`, `'EXPENSE'` mayúsculas — evidenced en `budget_lines.line_type`). SQLAlchemy resuelve el bind por nombre-then-valor, por eso el código actual filtra con `== "income"` y funciona. El label nuevo es **'PURCHASE'** (mayúsculas), espejo de los existentes.

### 3.2 Semántica de la fila compra (BR-PUR-01)

| Columna | Valor obligatorio |
|---|---|
| `line_type` | `purchase` |
| `behavior_type` | `fixed` (siempre; no existe "compra variable") |
| `budget_date` | **fecha de importación**, con `year == budgets.budget_year` (misma validación BR-LINE-04) |
| `payment_date` | **SIEMPRE NULL** — las cuotas se derivan en lectura, NUNCA se materializan (filosofía D-S7-2/BR-CO-04) |
| `id_collection` | NULL (no aplica) |
| `variable_rate` | NULL (no aplica) |
| `projected_amount` | valor total de la mercancía importada, COP neto, ≥ 0 |

### 3.3 Migración (única acción manual de despliegue)

```sql
ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';
```

- Ejecutar ANTES de subir el código nuevo (PG 16: `ADD VALUE` no puede correr dentro de transacción con uso posterior del valor en la misma transacción; `psql -c` autocommit es el camino — ejecutar ya en la dev: `docker exec db_crm_dev psql -U postgres -d crm -c "..."`).
- Documentar en `crm_backend/note.md` junto al precedente `include_carryover` (mismo patrón "ALTER manual requerido, create_all no altera").

### 3.4 Seguridad por diseño (verificar como aserción, no asumir)

Todos los consumidores existentes filtran por igualdad exacta `'income'`/`'expense'`, así que `purchase` queda fuera automáticamente en: `budgetEngine` (líneas 149/175/206/228/1005 — P&L, cash-flow legacy y Q5), `get_planning_scenarios` (CASE sums), `get_carryover_cogs_lines` (ingresos), vista Ejecutiva (FE). **Único filtro a blindar:** `get_carryover_lines` (§5.1 BE-S6) filtra `behavior_type == FIXED` sin `line_type` — añadir explícitamente `BudgetLineModel.line_type != LineTypeEnum.PURCHASE` (BR-CO-12: defensa determinista; hoy una compra nunca arrastra porque su `payment_date` es NULL y su `budget_date` ∈ N−1, pero el guard elimina la dependencia de esa invariante).

## 4. Derivación de cuotas (compartida FE/BE; el BE la implementa solo para arrastre)

`installments(compra) = [{date = budget_date + payment_days_i, amount = projected_amount × payment_pct_i} for term_i in line_payable_terms[id_line(CECO)] orden (payment_days ASC, id ASC)]`; si el CECO no tiene `id_line`, no tiene términos, o los pcts no suman 1: se aplica la cuota(s) tal cual (sin normalizar, espejo exacto de la derivación COGS de `get_carryover_cogs_lines` §4 BE-S7). Float crudo, cero redondeo intermedio (convención del repo).

## 5. Cambios por archivo

### 5.1 `app/crud/budget/planning.py`

1. **Guards en `create_planning_line` (BR-PUR-02):** payload con `line_type='purchase'` y (`behavior_type != FIXED` ∨ `id_collection is not None` ∨ `variable_rate is not None`) ⇒ 400 con detalle `{reason}` (`"purchase lines must be fixed with no collection and no variable rate"`); `payment_date` enviado ⇒ **se fuerza a NULL en silencio** (BR-PUR-03, amigable; documentado). Resto de validaciones intactas (FKs, año BR-LINE-04, commit único).
2. **Guards en `update_planning_line` (BR-PUR-04):** si la fila persistida es `purchase`: `payment_date` en el body ⇒ 400 `"payment dates of a purchase derive from the line's payable terms"`; `id_collection`/`variable_rate` enviados ⇒ 400 análogo al mensaje de BR-PUR-02. `budget_date` editable con validación de año vigente (permite corregir la fecha de importación).
3. **Nuevo `get_carryover_purchase_lines(db, id_budget_source, budget_year_target)` (BR-PUR-05):** cuotas derivadas (§4) de las compras del escenario fuente cuyo `year(payment_date) == N`; retorna dicts `PlanningCarryoverLine`-shape con `origin="purchase"`, `line_type="expense"`, `id_budget_line=None`, `budget_date`=fecha de importación, `payment_date`=cuota, `projected_amount`=cuota, `description="Pago a proveedor (arrastre)"`. Determinista: `id_budget_line ASC, (payment_days, id) ASC` generación.
4. **Switch de fuente en `build_carryover_payload_lines` (BR-PUR-06):** se computa el set de CECOs compradores de la FUENTE (1 query `SELECT DISTINCT id_cost_center WHERE line_type='purchase'`); `get_carryover_cogs_lines` EXCLUYE las filas de ingreso cuyo CECO sea comprador (parámetro `purchasing_cc_ids: set` a la función; no duplicar el derivado), y seMergean las `purchase` derivadas. Orden BR-CO-10 extendido: `(effective_date ASC, origin_rank {line:0, cogs:1, purchase:2}, id null-safe)`.
5. `get_carryover_lines`: guard §3.4-4.

### 5.2 `app/schemas/budget/planning.py`

- `PlanningCarryoverLine.origin: Literal["line", "cogs", "purchase"] = "line"`.
- `PlanningUploadResult` += `lines_purchase: int = 0`, `total_purchase: float = 0.0` (default-valores ⇒ respuesta compatible para clientes viejos; se pueblan solo si llegó `file_compras`).
- `PlanningLineCreate.line_type` acepta `purchase` (hereda del enum; actualizar el texto `description`).

### 5.3 `app/api/budget/planning.py` — upload (§5.1 BE-S4)

Nuevo Form field opcional `file_compras: Optional[UploadFile] = File(None)`. Flujo: si llega ⇒ `BudgetTemplates(compras_bytes).process_budget_plan_purchase()` → `build_purchase_line_records(db, records, id_budget, budget_year)` (nuevo builder en `app/services/budgetPlanningIngestion.py`, mismo patrón income/expense: resuelve CECO por primer token del código, missing_cost_centers se AGREGAN a la lista única de rechazo BR-ING-03, `_check_row_year` sobre la fecha de importación → 400 `found_years` con rollback total). Una fila Excel = una fila compra (sin expansión de cuotas jamás). Las compras entran al `create_budget_lines_bulk` de la misma transacción (T-05/B R-ING-01: todo o nada).

### 5.4 `app/utils/templates/budgetTemplates.py` — plantilla propia

Nuevo método `process_budget_plan_purchase()`: hoja única "Importaciones", **header en fila 1** (`pd.read_excel(header=0)`), columnas exactas (case-insensitive, espacios outer tolerados):

| Columna | Tipo | Obligatoria |
|---|---|---|
| `Centro de Costo` | string — se resuelve por PRIMER TOKEN (patrón builder income) | sí |
| `Fecha Importacion` | date (datetime de Excel o `dd/mm/yyyy`) | sí |
| `Valor` | float COP ≥ 0 | sí |
| `Descripcion` | string | no |

Filas totalmente vacías se ignoran; fila con columna obligatoria vacía/no parseable ⇒ error 400 estructurado con número de fila (patrón `_validate_data_integrity` simplificado — el rechazo es all-or-nothing). El archivo de plantilla física se entrega bajo `Plantillas/` del repo raíz (`Plantilla Plan de Importaciones.xlsx`) y su descarga queda PQ-BE-2.

## 6. API — contract delta (resumen)

| Endpoint | Cambio |
|---|---|
| `POST /budget/planning/upload` | + `file_compras` opcional multipart; resultado += `lines_purchase`, `total_purchase` |
| `POST /budget/planning/{id}/line` | acepta `line_type="purchase"` con guards §5.1-1 |
| `PUT /budget/planning/line/{id}` | guards §5.1-2 |
| `GET /budget/planning/{id}/carryover` | puede responder filas con `origin:"purchase"` |
| `PUT /cell/{id}`, DELETE/GET lines, clone, set-target, detail, dashboard | **sin cambios** (funcionan por genéricos) |

## 7. NFR

| ID | Requisito |
|---|---|
| NFR-BE8-1 | Cero escritura nueva de cuotas: las derivaciones son read-only (BR-CO-04 extendido a purchase) |
| NFR-BE8-2 | Economía de queries en carryover: +máx 2 consultas por request (set comprador + compras fuente), independientemente del # de filas |
| NFR-BE8-3 | Backward compat total: un escenario sin compras produce payloads byte-idénticos a hoy (origin "purchase" simplemente no aparece) |
| NFR-BE8-4 | Determinismo: órdenes estables explícitos (§5.1-4, §4) |

## 8. Riesgos/enmiendas futuras

* **R-BE-1:** el Pilar 2 (`get_cash_flow` Q5) sigue tomando solo `expense` como salidas del presupuesto ⇒ una compra presupuestada NO aparece en la curva de liquidez analítica hasta una enmienda. Documentado; la Vista Flujo del planning (fuente de verdad para este stakeholder) sí la refleja.
* **R-BE-2:** si `cogs_pct` está mal calibrado vs. compras reales, la bodega estimada diverge — el FE lo muestra con nota (no es problema de BE).
* **PQ-BE-1:** bodega inicial de N con arrastre ON (saldo = Σcompras−Σcostos de N−1). **PQ-BE-2:** endpoint de descarga de plantilla.

## 9. Criterios de aceptación (BE)

* **AC-BE8-1:** Tras el ALTER, `POST /{id}/line` con `line_type:"purchase"` persiste la fila (DB muestra `'PURCHASE'` mayúsculas) y el `GET /{id}/detail` la devuelve como `"purchase"`; con `behavior_type:"variable_sales"` ⇒ 400; con `payment_date` ⇒ persisted NULL.
* **AC-BE8-2:** `PUT /line/{id}` de una compra con `payment_date` en body ⇒ 400 con el detalle literal §5.1-2.
* **AC-BE8-3:** `get_pnl`, `project_cash_flow`, `get_cash_flow`, `GET /budget/planning/` (totales) y carryover de un escenario SIN compras: respuestas idénticas a pre-cambio (regresión por smoke actual).
* **AC-BE8-4:** Upload del planning con 3 archivos crea income+expense+purchase en una transacción; un CECO desconocido SOLO en el archivo de compras ⇒ 400 `missing_cost_centers` y rollback TOTAL; fecha de importación en año distinto ⇒ 400 `found_years`.
* **AC-BE8-5:** Escenario fuente N−1 con 1 compra (CECO comprador con términos 30/60 @ 0.5/0.5, importación 15/12/N−1) y flag ON en N: `GET /{id}/carryover` responde cuota 15/01/N `origin:"purchase"` 50 % + cuota 13/02/N 50 %, Y la derivación `cogs` para ese CECO **no** aparece (switch D-4); CECO no comprador conserva sus filas `cogs`.
* **AC-BE8-6:** `POST /clone` escala compras con el modifier (BR-CLN-02 aplica genérico) y NO copia behavior distinto de fixed.

**Prueba:** smoke estilo `crm_backend/test/test_budget_planning_lines_smoke.py` para AC-BE8-1/2/4/5 (patrón existente del repo), más migración ejecutada en la dev `db_crm_dev` (docker) y verificación `SELECT unn(enum_range(NULL::linetypeenum))`.

---

## 10. Enmienda A-01 (2026-09-16): plantilla real SIIGO + Temporada en compras

**Origen:** el stakeholder entregó la plantilla real `crm_backend/test/data/Formato Solicitud Presupuesto Importaciones.xlsx` (layout SIIGO: encabezados en fila 8) y exige `Temporada` en la compra — ingesta y manual — con la MISMA semántica que ingresos. Reemplaza §5.4 y los guards de §5.1/§5.2 donde colisionen.

### 10.1 `process_budget_plan_purchase` — nuevo layout (reemplaza §5.4)

- Lectura: `sheet_name=0` (primera hoja — el archivo real se llama "Requisición de Facturación" con errata visible; leer por POSICIÓN, nunca por nombre) con `skiprows=7` ⇒ encabezados en la **fila 8**, en par con income/expense. La segunda hoja "Tablas" (listas de validación) se ignora.
- Encabezados del archivo real (limpios): `centro_de_costo`, `nombre_del_colaborador`, `fecha_de_solicitud`, `fecha_importacion`, `temporada`, `monto`, `descripcion`.
- Mapeo: `centro_de_costo` → primer token (regla vigente); `fecha_importacion` → `budget_date` (datetime de Excel o texto dd/mm/yyyy — `_parse_import_date` vigente); `monto` → `projected_amount` (numérico ≥ 0, guard vigente); `temporada` → `short_collection_name` (strip, espejo income l.1400-1404); `descripcion` → `description` (opcional, None-safe vigente).
- `nombre_del_colaborador` y `fecha_de_solicitud` (fecha de SOLICITUD ≠ de importación): TOLERADOS y **ignorados** en v1 (PQ-BE-3: metadatos si se piden).
- `PURCHASE_REQUIRED_COLS` := `["centro_de_costo", "fecha_importacion", "temporada", "monto"]` — falta una columna ⇒ 400 `missing_columns`. El **valor** de `temporada` puede ser vacío/desconocido ⇒ NO bloquea (semántica income: `get_collection_by_short_name` desconocido ⇒ `id_collection=None`).
- Offset de fila Excel en `invalid_rows`: header en fila 8 ⇒ `excel_row = idx + 9` (antes +2).

### 10.2 Temporada como metadato de la compra (reemplaza BR-PUR-01..04 en lo colisionante)

- `build_purchase_line_records`: mapea `short_collection_name → id_collection` con el par exacto de income/expense (l.116-118); sigue **una fila = una compra** (la temporada jamás expande cuotas).
- `create_planning_line`: el guard purchase rechaza solo `behavior_type != FIXED` ∨ `variable_rate` ; `id_collection` **se permite** y pasa a la validación de existencia vigente (404 `"Collection {id} not found"`). Literal nuevo `PURCHASE_SHAPE_REASON`: `"purchase lines must be fixed with no variable rate"`.
- `update_planning_line`: en fila purchase persistida, `id_collection` enviado ⇒ permitido (404 si no existe); `payment_date` y `variable_rate` siguen 400 (mensajes vigentes).
- Invariante CONFIRMADA: `payment_date` de compra SIEMPRE NULL; las cuotas siguen derivándose de `line_payable_terms` ancladas a la fecha de importación. `PlanningLineCreate`/`BudgetLineBase`: actualizar `description` (compras admiten temporada).

### 10.3 Plantilla física

Reemplazar `Plantillas/Plantilla Plan de Importaciones.xlsx` por una copia del formato real entregado (ambas hojas, fila 8 con encabezados y la fila de ejemplo limpia o con placeholders).

### 10.4 AC de la enmienda

- **AC-BE8a-1:** parsear el fixture real (`test/data/Formato Solicitud...xlsx`) produce N records con `short_collection_name` y sin `payment_date`; `POST /upload` con ese archivo crea las compras con `id_collection` resuelto para temporadas del catálogo y `None` para desconocidas (201, no 400).
- **AC-BE8a-2:** `POST /{id}/line` purchase con `id_collection` válido ⇒ 201 persistida con temporada; id inexistente ⇒ 404; `variable_rate` ⇒ 400 con el literal NUEVO.
- **AC-BE8a-3:** `PUT /line/{id}` de compra con `id_collection` ⇒ 200 y temporada cambiada; con `payment_date` ⇒ sigue 400 con el literal vigente.
- **AC-BE8a-4:** columnas obligatorias ausentes en el xlsx ⇒ 400 `missing_columns`; fila sin fecha ⇒ 400 `invalid_rows` con `row` = fila Excel real (idx+9); regresión: los AC-BE8-1..6 siguen (actualizando el smoke donde el guard cambió de mensaje/permitió temporada).

---

## 11. Enmienda A-02 (2026-09-16): el switch de fuente pasa de por-CECO a **por-Línea** (D-4')

**Defecto reportado:** escenario 266 (2026): compras en CECO `000001` (Facturación Kyly) y `000002` (Facturación Tinta); ingresos en CECOs de ZONA `000101/000201` (Kyly) y `000202/000302` (Tinta). Como el switch D-4 comparaba CECO-comprador contra CECO-vendedor, nunca casaba ⇒ el bloque "Pago a proveedores" mostraba las cuotas de compra (43M) **MAS** las cuotas derivadas de ingreso (47M × 60% = 28.2M) — doble cuenta del mismo pago económico. El comercio real registra la importación en el CECO "Facturación {Línea}" y vende en los CECOS zonales de ESA MISMA LÍNEA (verificado: ambos grupos comparten `id_line` 1/2; los términos y tasas también son por Línea).

### 11.1 Regla D-4' (reemplaza el conjunto de aplicación de BR-PUR-06 y el switch FE)

Clave de fuente de un CECO: `KEY(cc) = "line:" + cc.id_line` si el CECO tiene `id_line`; si NO tiene ⇒ `KEY(cc) = "cc:" + cc.id_cost_center` (unidad propia — dos CECOs sin línea jamás se switchan entre sí).

- `K = { KEY(cc) : cc tiene ≥1 fila purchase en el escenario }`.
- Cuota derivada por INGRESO (FE-S7 / `cogs` carryover) aplica solo a filas de ingreso con `KEY(cc) ∉ K`.
- Cuota derivada por COMPRA aplica a toda fila purchase (fuente "purchase" / bloque FE).
- Consecuencia: por cada Línea (o CECO sin línea) existe EXACTAMENTE una fuente de pago a proveedores. Una compra en cualquier CECO de la Línea (típico: el CECO "Facturación") apaga la derivación por ingreso de TODOS los CECOS de esa Línea (zonales incluidos). Un escenario sin compras ⇒ `K=∅` ⇒ comportamiento FE-S7 intacto (NFR-BE8-3).

### 11.2 Cambios BE (carryover espejo de la regla)

- `get_purchasing_cc_ids` → derivar **claves** (nombre a criterio del implementador, p. ej. `get_purchasing_source_keys`): 1 query (purchase JOIN cost_centers ⇒ `DISTINCT id_line` + `id_cost_center` para compras sin línea). NFR-BE8-2 sigue: +0/2 queries.
- `get_carryover_cogs_lines`: el parámetro `purchasing_cc_ids` pasa a ser la estructura de claves; exclusión SQL/Python exacta: fila ingreso se excluye si (`id_line` ∈ purchasing_lines) ∨ (`id_line IS NULL ∧ id_cost_center` ∈ purchasing_ccs). El join a `CostCenterModel` ya existe (resuelve `id_line` de la tasa) — sin query extra.
- `build_carryover_payload_lines`: usa las claves sobre la FUENTE (misma D-4', mismo escenario fuente).
- Docstring de `planning.py` (API): redacción del switch ⇒ "por Línea (claves line:/cc:)".

### 11.3 AC de la enmienda

- **AC-BE8b-1:** escenario fuente con compra en CECO "Facturación X" (id_line=L) e ingreso en CECO zonal de la MISMA L: carryover del año siguiente responde SOLO origen `purchase` para ambas caras (cero `cogs` de la L); un CECO de otra Línea sin compras conserva su `cogs`.
- **AC-BE8b-2:** compra en CECO SIN `id_line` ⇒ solo switcha filas de ingreso de ESE CECO (cc:); no toca otros CECOS sin línea.
- **AC-BE8b-3:** escenario fuente sin compras ⇒ payload idéntico a A-01 (regresión).
- **AC-BE8b-4 (266 end-to-end):** `GET /budget/planning/266/carryover` con flag OFF ⇒ enabled:false (sin cambio); la regla aplica al render FE (ver frontend.03_12 §7); BE: smoke purchases actualizado (44+ checks) sin romper los 43 existentes.
