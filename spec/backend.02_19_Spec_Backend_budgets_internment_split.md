# Spec Backend: Desglose proveedor + internación del costo de compra (split)

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S9-INTERNMENT-SPLIT` |
| **Espec counterparts** | FE: `frontend.03_13` (FE-S10-INTERNMENT-SPLIT). Bases: BE-S8 (`02_18` + enmiendas A-01/A-02), BE-S7 (`02_17`), BE-S5 (`02_15`) |
| **Tablas nuevas** | 2: `line_internment_rates`, `line_internment_terms` |
| **DDL requerido** | **NINGUNO** — `create_all` crea tablas nuevas; cero ALTER (contraste BE-S8 §3.3: por eso son tablas satélite nuevas y NO columnas en `lines`, que requerirían DDL manual) |
| **Convenciones** | T-03 legacy `db.query`, T-05 un solo commit, camelCase filenames, checklist de 4 puntos de registro × 2 entidades |
| **Fecha** | 2026-09-21 (sesión stakeholder — registro de decisiones §1.1) |

---

## 0. Problema

El `projected_amount` de una compra **ya es el costo total**: incluye la factura del proveedor Y la internación de la mercancía (nacionalización/aranceles/logística). Hoy el 100 % de ese valor se trocea como "cuotas al proveedor" con `line_payable_terms`, sobrestimando el pago al proveedor y haciendo invisible la internación, que se paga a otro destinatario y en plazos distintos (patrón habitual: 60 % a +15 d y 40 % a +45 d).

## 1. Modelo conceptual

```
COMPRA (budget_lines line_type=purchase; projected_amount = CostoTotal COP)
  ├─ %int   = line_internment_rates de la Línea del CECO (fracción 0-1 = recargo SOBRE el proveedor)
  ├─ CostoProveedor      = total / (1 + %int)      → cuotas line_payable_terms (mecánica intacta, NUEVA base)
  ├─ CostoInternación    = total − CostoProveedor  → cuotas line_internment_terms (catálogo NUEVO)
  └─ Ancla de ambos stream = budget_date = fecha de importación (fecha_cuota = ancla + payment_days)

Línea sin %int configurado ⇒ %int = 0 ⇒ CostoProveedor = total ⇒ comportamiento actual byte-idéntico (NFR-BE9-3)
P&L / Ejecutiva / Bodega / ingesta / plantillas / ruta cogs (ingreso×cogs_pct): INTOCADOS —
  projected_amount sigue leyéndose como costo total; el cogs_pct ya incorpora internación por construcción.
Cuotas NUNCA se materializan (D-S7-2 extendido): solo derivación en lectura.
```

### 1.1 Registro de decisiones y supuestos aprobados (sesión 2026-09-21 — fuente de trazabilidad)

| ID | Decisión | Origen |
|---|---|---|
| A-1' | `projected_amount` = costo TOTAL (proveedor + internación); el sistema DESCOMPONE, no agrega | Stakeholder (supuesto 1 corregido) |
| D-S9-1 | % internación expresado como recargo sobre el proveedor: `Total = Prov × (1 + %)`; descomposición `Total / (1 + %)` | Stakeholder, opción 1 |
| A-2 | % y plazos de internación se configuran por Línea de producto (catálogo), no por renglón de compra | Supuesto aprobado |
| A-3 | Ancla de plazos de internación = fecha de importación (`budget_date`), igual que proveedor | Supuesto aprobado |
| A-4 | 60 %/15 d + 40 %/45 d es solo default de UI al crear términos; cada Línea admite N cuotas | Supuesto aprobado |
| A-5 | Línea sin % ⇒ 0 ⇒ cero filas de internación (sin default global, sin bloqueo) | Supuesto aprobado |
| A-6 | Bloque de salida separado "Pago de internación" en Flujo; cuotas nunca materializadas | Supuesto aprobado |
| A-7 | Carryover incluye cuotas de internación, filtradas por año de cada vencimiento | Supuesto aprobado |
| A-8 | Alcance v1: solo fuente PURCHASE; ruta cogs y P&L intactos | Supuesto aprobado |
| A-9 | Sin normalización ni validación de suma de pct = 1 (espejo BE-S8 §4) | Supuesto aprobado |
| A-10 | Misma moneda de la compra; cero columnas nuevas en plantillas SIIGO | Supuesto aprobado |
| A-11 | Cero cuentas por pagar automáticas al logístico; `accounts_payable` queda manual | Supuesto aprobado |
| PQ-S9-4 | % por Línea sin vigencia por fechas (valor vigente único) | Arquitecto (espejo payable; vigencia ⇒ PQ-S9-3) |

## 2. Alcance

**Incluye:** (1) dos tablas + CRUD REST de los catálogos; (2) re-semantización de la derivación §4 BE-S8 (base stream proveedor) + stream nuevo de internación; (3) carryover con `origin:"internment"` y extensión del rank BR-CO-10; (4) smoke.
**Excluye (v1):** P&L/`budgetEngine`/bodega/compras del mes; ruta ingreso×cogs_pct con internación; materialización de cuotas; AP automáticos al agente de aduanas (PQ-S9-2); flujo Pilar 2 (R-BE-1 heredado); cambios de plantillas; % con vigencia (PQ-S9-3); override por renglón (PQ-S9-5).

## 3. Modelo de datos

### 3.1 `line_internment_rates` — % de internación por Línea (`app/models/budget/lineInternmentRate.py`)

```python
class LineInternmentRate(Base):
    """Internment-cost rate of a product line (mark-up on supplier cost)."""
    __tablename__ = "line_internment_rates"

    id_line_internment_rate = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False, unique=True)
    internment_pct = Column(Float, nullable=False)   # fraction 0-1; D-S9-1
```

Schemas `LineInternmentRateBase/Create/LineInternmentRate` (triple estándar, `model_config = ConfigDict(from_attributes=True)`): `id_line: Field(gt=0)`; `internment_pct: Field(gt=0, le=1)` — el 0 exclusivo porque la ausencia se representa BORRANDO la fila (rationale espejo de `linePayableTerm.py` docstring), y `le=1` porque un recargo >100 % está fuera del rango comercial de internación (se enmienda si un stakeholder lo pide). Unicidad por Línea: guard en CRUD → 400 amable ANTES del IntegrityError (el `unique=True` genera el índice en `create_all`, pero el mensaje útil es del CRUD).

### 3.2 `line_internment_terms` — cuotas de pago de la internación por Línea (`app/models/budget/lineInternmentTerm.py`)

Copia EXACTA de forma/orden/validaciones de `line_payable_terms`:

```python
class LineInternmentTerm(Base):
    __tablename__ = "line_internment_terms"

    id_line_internment_term = Column(Integer, primary_key=True, index=True)
    id_line = Column(Integer, ForeignKey("lines.id_line"), nullable=False)
    payment_pct = Column(Float, nullable=False)     # fracción 0-1: multiplica el CostoInternación
    payment_days = Column(Integer, nullable=False)  # offset desde fecha de importación
```

Schema: `payment_pct: Field(gt=0, le=1)`, `payment_days: int` (negativos permitidos como en proveedor; el patrón típico es positivo). Docstring obligatorio aclarando la diferencia SEMÁNTICA con `line_payable_terms`: la base es el `internment_cost`, no el monto total de la fila — las tablas NO son intercambiables.

### 3.3 Checklist de 4 puntos de registro (× 2 entidades, espejo exacto de `linePayableTerm`)

1. `app/models/budget/__init__.py` (patrón l.12) → `app/models/__init__.py` (bloque budget, l.41).
2. `app/schemas/budget/__init__.py` (l.24, imports nombrados explícitos) → `app/schemas/__init__.py` (l.62, `LineInternmentRate, LineInternmentRateCreate, LineInternmentTerm, LineInternmentTermCreate`).
3. `app/crud/budget/__init__.py` (l.12): `from .lineInternmentRate import *` y `from .lineInternmentTerm import *`.
4. `app/api/budget/__init__.py` (l.20 + `include_router(..., prefix="/line-internment-rate", tags=["budget"])` y `prefix="/line-internment-term"`, patrón l.65). `app/main.py` NO cambia (el agregador `budget` ya está montado).

## 4. Derivación de cuotas (compartida FE/BE — reemplaza §4 BE-S8 para la fuente purchase)

Por cada compra: `total = float(projected_amount)`, `L = id_line(CECO)` (`None` ⇒ sin Línea), `pct = internment rate de L` (sin fila o sin L ⇒ 0):

```python
costo_prov = total / (1.0 + pct)
costo_int  = total - costo_prov                    # == total × pct/(1+pct), BR-INT-01

cuotas_prov = [{date = anchor + term.payment_days, amount = costo_prov × term.payment_pct}
               for term in line_payable_terms[L] orden (payment_days ASC, id ASC)]
              # SIN términos / sin id_line ⇒ cuota única 100 % de costo_prov en el anchor (D-S7-4, nueva base)

cuotas_int  = pct == 0 ⇒ []                        # BR-INT-05 (A-5)
              CON términos ⇒ [{date = anchor + term.payment_days, amount = costo_int × term.payment_pct}
                              for term in line_internment_terms[L] orden D-7]
              SIN términos ⇒ cuota única 100 % de costo_int en el anchor   # BR-INT-04 (D-S7-4 mirror)
```

Ancla = `budget_date` (fecha de importación) para AMBOS streams (A-3). Guardas heredados de BE-S8 §4 sin cambios: pct aplicado tal cual (sin normalizar, A-9), float crudo, cero redondeo intermedio, orden D-7 (`payment_days ASC, id ASC`).

Casos borde:

| Caso | Stream proveedor | Stream internación |
|---|---|---|
| Línea sin % (A-5) | 100 % del total (idéntico a hoy) | cero filas |
| % > 0, sin int-términos | según sus términos | 1 fila única 100 % en la ancla |
| CECO sin `id_line` | cuota única 100 % del total (pct irresoluble ⇒ 0; D-S7-4 hoy) | cero filas |
| % = 1 (tope le=1) | 50 % | 50 % |

## 5. Cambios por archivo

### 5.1 `app/crud/budget/lineInternmentRate.py` (nuevo; T-03/T-05)
`get_line_internment_rates(db)` (catálogo completo orden `id_line`), `get_line_internment_rate_by_line(db, id_line) -> model | None`, `create` (devuelve `None` si la Línea ya tiene tasa ⇒ la capa API resuelve 400), `update`, `delete` (físico, catálogo sin historial). Un solo commit por mutación (T-05).

### 5.2 `app/crud/budget/lineInternmentTerm.py` (nuevo)
Espejo exacto de `crud/budget/linePayableTerm.py`: full list, `by_line` en orden D-7, create/update/delete, borrado físico con comentario de que la derivación degrada a la cuota única BR-INT-04.

### 5.3 `app/api/budget/lineInternmentRate.py` y `app/api/budget/lineInternmentTerm.py` (nuevos)
Stack JWT (`get_db` + `get_current_user`, sin role gate), pre-chequeos de FK con literal `"Line {id_line} not found"` (404), resolución Optional→404 en esta capa — todo espejo de `api/budget/linePayableTerm.py` (mismos comentarios de convenio). Verbos y literales:
- **Rate:** `GET /` (List) · `GET /by-line/{id_line}` → objeto o `null` 200 (la ausencia NO es error) · `POST /` 201; duplicado ⇒ **400 `"Line {id_line} already has an internment rate"`** · `PUT /{id_line_internment_rate}` full-replacement; inexistente ⇒ 404 `"LineInternmentRate {id} not found"`; re-parentear a Línea con tasa existente ⇒ 400 literal análogo · `DELETE /{id}` ⇒ `{"deleted_id": id}` (404 mismo literal).
- **Term:** cinco verbos idénticos a payable-term (`GET /`, `GET /by-line/{id_line}` ⇒ `[]` si no hay, `POST` 201, `PUT /{id}` 404 `"LineInternmentTerm {id} not found"`, `DELETE /{id}` ⇒ `{"deleted_id": id}`), 422 por `Field` validators.

### 5.4 `app/crud/budget/planning.py`
1. **`get_carryover_purchase_lines` (BR-INT-06, extiende BR-PUR-05):** la query + regrouping actuales quedan IGUALES; tras el regrouping, 2 queries batch (NFR-BE9-2): tasas `{id_line: pct}` (IN sobre el set de Líneas de las compras) y `line_internment_terms` (IN, orden SQL `id_line, payment_days, id`). El loop de cuotas se reemplaza por la fórmula §4: stream proveedor conserva `origin="purchase"` + `PURCHASE_CARRYOVER_DESCRIPTION` con base `costo_prov`; stream internación emite dicts idénticos pero `origin="internment"` + `INTERNMENT_CARRYOVER_DESCRIPTION`. Filtro de año BR-CO-09 por cuota, aplicado a AMBOS streams (A-7). Determinismo (NFR-BE8-4): dentro de una fila, stream proveedor se genera antes que el de internación.
2. Constante nueva `INTERNMENT_CARRYOVER_DESCRIPTION = "Pago de internación (arrastre)"`.
3. **`_carryover_order_key` (BR-CO-10 extendido):** rank `{"line": 0, "cogs": 1, "purchase": 2, "internment": 3}`.
4. `get_carryover_cogs_lines`, `get_carryover_lines`, `build_carryover_payload_lines` (claves D-4'): **intactos** — la internación solo nace de la fuente purchase (A-8); el switch de fuente no cambia (una compra en la Línea ya la hace "compradora"; sus filas purchase ahora se dividen en dos streams).
5. Docstrings del line manager (`create_planning_line`/`update_planning_line`) y del módulo API: una línea mencionando la descomposición §4. **Cero cambio de comportamiento de la fila:** guards BR-PUR-02/03/04 intactos, `payment_date` sigue NULL.

### 5.5 `app/schemas/budget/planning.py`
- `PlanningCarryoverLine.origin: Literal["line", "cogs", "purchase", "internment"] = "line"` + docstring del contrato (base desglosada §4).
- `PlanningUploadResult`: sin claves nuevas (la fila no cambió de forma).

## 6. API — contract delta (resumen)

| Endpoint | Cambio |
|---|---|
| `GET/POST /budget/line-internment-rate/`, `GET /by-line/{id_line}`, `PUT/DELETE /{id}` | **NUEVO** (catálogo §5.3) |
| `GET/POST /budget/line-internment-term/`, `GET /by-line/{id_line}`, `PUT/DELETE /{id}` | **NUEVO** (catálogo §5.3) |
| `GET /budget/planning/{id}/carryover` | puede responder filas `origin:"internment"`; las filas `origin:"purchase"` ahora suman SOLO el componente proveedor |
| lines CRUD, upload, cell, clone, set-target, detail, dashboard, P&L, legacy cash flow | **sin cambios** |

## 7. NFR

| ID | Requisito |
|---|---|
| NFR-BE9-1 | Cero escritura/materialización de cuotas (D-S7-2/BR-CO-04 extendidos a internación); los únicos datos nuevos son los catálogos |
| NFR-BE9-2 | Economía de queries del carryover: +≤2 consultas por request (tasas IN + términos IN sobre el set de Líneas), independiente del # de filas |
| NFR-BE9-3 | Backward compat total: escenario con compras cuyas Líneas no tienen %int (estado hoy: no existe ninguna fila) ⇒ payloads byte-idénticos a BE-S8; el smoke `test_budget_purchases_smoke.py` sigue verde salvo el conteo SELECT NFR-BE8-2 (6→8, Nota §10) |
| NFR-BE9-4 | Determinismo: órdenes estables explícitos (§4 D-7, rank §5.4-3, `id_budget_line ASC`, stream prov→int) |
| NFR-BE9-5 | Cero DDL manual de despliegue (contraste BE-S8 §3.3): subir código, `create_all` crea las 2 tablas |

## 8. Riesgos / enmiendas futuras

- **R-S9-1:** si `Σ pct_prov ≠ 1` o `Σ pct_int ≠ 1`, proveedor+internación no cuadran al total — aceptado (A-9, espejo BE-S8 §4); el panel FE muestra aviso de Σ (frontend.03_13 §2.3c).
- **R-S9-2:** Líneas no-compradoras (ruta `ingreso × cogs_pct`) no tienen internación explícita: el `cogs_pct` se calibra desde costos reales SIIGO (costo total ⇒ ya la incorpora). Si se demuestra lo contrario ⇒ enmienda que extienda §4 a la ruta cogs.
- **R-S9-3:** clientes FE viejos que reciban `origin:"internment"` colapsan el label a "line" (normalización FE-S9 §2.7) — montos igual de correctos, solo label degradado. Deploy coordinado BE+FE (mismo repo) ⇒ aceptado.
- **PQ-S9-2:** generación automática de `accounts_payable` al operador logístico con las cuotas int. **PQ-S9-3:** tasa con vigencia (`date_from/date_to`, patrón `line_cost_rates`). **PQ-S9-5:** override del % a nivel renglón de compra. **PQ-S9-6:** internación en el flujo analítico Q5 (ligado a R-BE-1).

## 9. Criterios de aceptación (BE)

- **AC-BE9-1 (catálogo rate):** POST `{id_line: 1, internment_pct: 0.20}` ⇒ 201; segundo POST sobre `id_line 1` ⇒ 400 `"Line 1 already has an internment rate"`; `internment_pct: 1.5` ⇒ 422; `0` ⇒ 422; `GET /by-line/{line}` sin tasa ⇒ 200 `null`; PUT con `id_line` inexistente ⇒ 404 `"Line {id} not found"`; DELETE ⇒ `{"deleted_id": n}` y el by-line vuelve `null`.
- **AC-BE9-2 (catálogo term):** espejo de AC-S5-BE sobre `/by-line` (orden D-7; `[]` si ausencia; 422 pct ∉ (0,1]; FK 404; DELETE responde id).
- **AC-BE9-3 (desglose end-to-end):** fixture: compra 120 000 000, importación 15/12/2026, Línea con rate 0.20, términos proveedor `+30 @ .5 / +60 @ .5`, términos internación `+15 @ .6 / +45 @ .4`; escenario objetivo 2027 con flag ON ⇒ `GET /{id}/carryover` responde EXACTAMENTE 3 filas con fecha en 2027: `origin:"purchase"` 14/01/2027 50 000 000, `origin:"purchase"` 13/02/2027 50 000 000, `origin:"internment"` 29/01/2027 8 000 000 (la cuota int 12 000 000 del 30/12/2026 queda EXCLUIDA por BR-CO-09); descripciones literales "Pago a proveedor (arrastre)" / "Pago de internación (arrastre)"; cero filas `cogs` de esa Línea (switch D-4' intacto, espejo AC-BE8-5).
- **AC-BE9-4 (regresión):** Línea SIN rate ⇒ cuotas `purchase` con montos idénticos a pre-cambio; escenario sin compras ⇒ payload byte-idéntico; smoke purchases intacto salvo el conteo 6→8 de la Nota §10.
- **AC-BE9-5 (edge, nivel crud en el smoke):** pct > 0 y cero int-términos ⇒ UNA fila `internment` al 100 % del `costo_int` en la fecha de importación; pct = 0 ⇒ cero filas `internment`; términos int con `payment_days` que cae en año objetivo ⇒ incluida.
- **AC-BE9-6 (rank empate):** cuota purchase e internment con idéntica fecha efectiva ⇒ la `internment` ordena DESPUÉS (rank 3 sobre 2).
- **AC-BE9-7 (fila intacta):** `GET /{id}/detail` y guards del line manager byte-idénticos (sin campos nuevos en la línea).

**Prueba:** smoke nuevo `crm_backend/test/test_budget_internment_smoke.py` (patrón purchases smoke, estilo BE-S8 §9) cubriendo AC-BE9-1..7, más corrida del purchases smoke existente sin modificar (NFR-BE9-3). Verificación post-arranque: `\dt` muestra las 2 tablas; `SELECT COUNT(*)` cero.

---

## 10. Nota de implementación (2026-09-21, post-despliegue BE-S9)

1. **NFR-BE9-3 / AC-BE9-4 (ajuste único):** la aserción medida de NFR-BE8-2 en `test_budget_purchases_smoke.py` (t11c) pasa de `6 → 8` SELECTs con compras — los 2 queries batch de §5.4-1 son obligatorios y constantes; la ruta sin compras sigue en 5 (batches se omiten con el set de Líneas vacío). TODAS las demás aserciones (payloads, montos, órdenes, paridad HTTP-vs-unit, AC-BE8-*) quedan intactas y verdes — la compatibilidad byte-idéntica del payload sin configuración es la garantía sustantiva de NFR-BE9-3.
2. **Gate de §4:** el stream de internación se emite con `pct > 0 Y costo_int > 0` — idéntico a BR-INT-05 para compras no nulas y adicionalmente protege contra filas fantasma en compras de monto 0.
3. **Docstring de `build_carryover_payload_lines`:** actualizado con el rank `{line:0, cogs:1, purchase:2, internment:3}` y el presupuesto +4 (era el docstring obsoleto señalado por la implementación).
4. **Espejo FE:** `frontend.03_13` (FE-S10) consume los contratos §5.3/§6 byte-idénticos (`internment_pct`, D-7 por `id_line_internment_term`, `origin:"internment"`, descripción literal `"Pago de internación (arrastre)"`).
