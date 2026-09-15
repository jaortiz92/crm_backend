# Spec Backend: Términos de Pago a Proveedores por Línea (desglose del flujo de costos)

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S5-PAYABLE-TERMS` |
| **Versión** | 1.0 — 2026-09-14 |
| **Base** | BE-S4 (`backend.02_12` §5.1 ingesta planning) y BE-S4D (`backend.02_13` POST `/{id_budget}/line`). MODIFICA `build_expense_line_records` con flag OPT-IN y el POST de línea manual. NO toca la ingesta legacy `POST /budget/upload/budget-plan-expense` (AC-REG-01), ni el PUT de celda, ni el lado ingresos. |
| **Contrato** | Autoridad para `frontend.03_08_Spec_frontend_payable_terms.md` (FE-S5). |
| **Componentes** | NUEVOS `app/models/budget/linePayableTerm.py`, `app/schemas/budget/linePayableTerm.py`, `app/crud/budget/linePayableTerm.py`, `app/api/budget/linePayableTerm.py`; MODIFICAN `app/services/budgetPlanningIngestion.py`, `app/api/budget/planning.py`, `app/schemas/budget/planning.py` y los `__init__.py` de registro |
| **Dependencias** | Cero (SQLAlchemy + `Base.metadata.create_all`; registro en los 4 puntos de convención) |
| **Origen** | Sesión spec-definer 2026-09-14: historia "quiero ver el flujo de los costos desglosado por términos de pago (30 % a −60 días de la importación, 70 % el día de la importación; cambia por Línea)" + supuestos 1–12 aprobados. **Aclaración del stakeholder que fijó el diseño:** `line_payment_rules` describe cómo los CLIENTES nos pagan (cobro) y NO puede reutilizarse para lo que debemos pagar. |

---

> ⚠️ **ENMENDADO por ackend.02_17 (2026-09-14):** la expansión de gastos (BR-TERM-02..04/07/09) y expanded_siblings (§7) quedan RETIRADAS; la tabla line_payable_terms y su CRUD PERMANECEN re-semantizados como términos de pago al proveedor del COSTO de ventas. El texto debajo aplica SOLO en lo no contradicho.

## 1. Objetivo

Hoy los gastos del escenario se guardan con UN solo `payment_date` (el que viene del archivo SIIGO), así que el flujo de caja de costos se ve como un bulto en una fecha. Esta feature introduce el catálogo de **términos de pago a proveedores por Línea** y **explota las líneas de gasto fijas en cuotas** (una `budget_line` por término), para que "Vista Flujo", totales del Editor y cualquier consumidor de la caché reflejen CUÁNDO sale realmente el efectivo (p. ej. 30 % sesenta días antes de la importación y 70 % el día de la importación).

## 2. Alcance

**Incluye:** tabla nueva `line_payable_terms` + CRUD REST; expansión en la ingesta planning de egresos; expansión en la creación manual de línea de gasto (`POST /budget/planning/{id_budget}/line`) con respuesta extendida; reglas BR-TERM-01..10; smoke.

**Excluye (v1):** términos por proveedor individual (la Línea es el proxy — supuesto 3); re-expansión de escenarios existentes (solo al rehacer la carga SIIGO — supuesto 12); expansión de gastos variables (supuesto 7); agrupar visualmente cuotas hermanas en el Editor (queda en PQ-FD-1 de FE-S4D); validación de suma ≠ 100 % (supuesto 10, ver R-S5-2); columna "fuera de año" en Vista Flujo (R-S5-1); cambios en el lado ingresos/cobro (usa `line_payment_rules`, intacto); IVA; escenario `payment_terms_change` del motor analítico (otro dominio).

## 3. Modelo de datos — tabla `line_payable_terms`

Archivo `app/models/budget/linePayableTerm.py` (camelCase), clase `LinePayableTerm`, registrado en `app/models/budget/__init__.py` y `app/models/__init__.py`:

| Columna | Tipo | Reglas |
|---|---|---|
| `id_line_payable_term` | Integer PK, index | auto |
| `id_line` | Integer FK `lines.id_line`, **nullable=False** | una Línea puede tener N términos (0 ⇒ sin expansión) |
| `payment_pct` | Float, nullable=False | **fracción 0–1** (mismo semántica que `line_payment_rules.payment_pct`: el monto se MULTIPLICA por ella). Validación en schema: `gt=0, le=1` |
| `payment_days` | Integer, nullable=False | offset en días desde `budget_date` (ancla = fecha de importación). **Negativo = antes** (−60), 0 = el día, positivo = después |

Sin relaciones ORM nuevas (catálogo plano, resuelto por `id_line` igual que el legado).

### 3.1 Schemas (`app/schemas/budget/linePayableTerm.py`, registro explícito en `app/schemas/__init__.py`)

- `LinePayableTermBase`: `id_line: int`, `payment_pct: float = Field(..., gt=0, le=1)`, `payment_days: int`.
- `LinePayableTermCreate(LinePayableTermBase)`.
- `LinePayableTerm(LinePayableTermBase)`: `id_line_payable_term: int = Field(..., gt=0)`.
- `app/schemas/budget/planning.py`: `PlanningLineCreateResult(BudgetLine)` con `expanded_siblings: List[BudgetLine] = []` (§7).

## 4. Reglas de negocio

- **BR-TERM-01 (ancla):** `payment_date_cuota = budget_date + payment_days`. La ancla es la fecha proyectada del gasto (= fecha de importación/causación prevista, supuesto 1). La cuota puede caer en otro año (2026-02-01 + −60 → 2025-12-03): LEGAL, igual que una fecha de pago en enero+1; `BR-ING-06` (año del escenario) se evalúa SOLO sobre `budget_date`, intacto.
- **BR-TERM-02 (elegibilidad):** se explota únicamente una línea de gasto si `line_type == 'expense'` ∧ `behavior_type == 'fixed'` ∧ el CECO tiene `id_line` no nulo ∧ `line_payable_terms` tiene ≥1 fila para esa Línea. Cualquier otro caso ⇒ comportamiento actual byte-a-byte (BR-TERM-10).
- **BR-TERM-03 (caso único-0):** exactamente UN término con `payment_days == 0` ⇒ UNA línea, `payment_date = budget_date`, monto íntegro (sin multiplicar por pct). Espejo del mismo caso especial del ingreso (`budgetPlanningIngestion.py:112-113`) — coherencia de motor (D-4).
- **BR-TERM-04 (expansión):** N términos (distinto del caso 3) ⇒ N filas `budget_lines`: `projected_amount = monto_original × payment_pct` (cada cuota), `budget_date` IDÉNTICO en todas (causación no se mueve ⇒ P&G/Ejecutiva por causación quedan invariantes, supuesto 6), `payment_date` propia (BR-TERM-01), `id_collection`/`description`/`behavior_type` replicados; el `payment_date` del archivo/payload se IGNORA.
- **BR-TERM-05 (suma ≠ 100 %):** se aplica cada pct tal cual; sin validación ni residuo sintético en v1 (supuesto 10). Consecuencia aceptada: el Σ del flujo puede no cuadrar con el Σ de causación (R-S5-2).
- **BR-TERM-06 (opt-in planning-only):** `build_expense_line_records(..., expand_payable_terms: bool = False)`; `True` SOLO lo pasan `POST /budget/planning/upload` (`planning.py:136`) y el POST manual de línea. Las rutas legacy (`upload.py:416`) siguen llamando sin el flag ⇒ salida idéntica garantizada (AC-REG-01) y protegida por AC-S5-BE-5.
- **BR-TERM-07 (nunca re-explotar):** `clone`, `PUT /line/{id}` y `PUT cell` JAMÁS re-explotan: las filas ya materializadas SON las cuotas; re-explotarlas las multiplicaría (D-2). Supuesto 12: la re-expansión solo ocurre reconstruyendo desde Excel (nueva carga).
- **BR-TERM-08 (variables):** gastos `variable_sales`/`variable_receivables` (monto 0 + tasa) nunca se explotan (supuesto 7).
- **BR-TERM-09 (transaccionalidad):** la expansión del POST manual ocurre en la MISMA transacción: o se crean todas las cuotas o ninguna (cualquier 4xx/5xx ⇒ rollback total, sin huérfanas).
- **BR-TERM-10 (sin términos ⇒ intacto):** CECO sin Línea, Línea sin términos o gasto no-elegible: una sola fila con el `payment_date` recibido (o `budget_date` si null), exactamente como hoy.

## 5. API — CRUD de términos (router `linePayableTerm`)

Montado en el agregador budget: `budget.include_router(line_payable_term_router, prefix="/line-payable-term", tags=["Line Payable Terms"])` en `app/api/budget/__init__.py` (patrón de `line-cost-rate`; `main.py` ya incluye `budget`). Política de autenticación/roles: LA MISMA que los endpoints de `app/api/budget/lineCostRate.py` (espejar dependencias al implementar).

| Verbo | Ruta | Éxito | Errores |
|---|---|---|---|
| GET | `/budget/line-payable-term/` | `List[LinePayableTerm]` (catálogo completo, orden `id_line, payment_days`) | — |
| GET | `/budget/line-payable-term/by-line/{id_line}` | `List[LinePayableTerm]` (`[]` si no hay — NO es 404) | — |
| POST | `/budget/line-payable-term/` | 201 `LinePayableTerm` | 422 (pct ∉ (0,1], días no entero); 404 `"Line {id_line} not found"` si la Línea no existe |
| PUT | `/budget/line-payable-term/{id}` | 200 `LinePayableTerm` | 404 `"LinePayableTerm {id} not found"`; 422 |
| DELETE | `/budget/line-payable-term/{id}` | `{"deleted_id": id}` | 404 `"LinePayableTerm {id} not found"` |

CRUD en `app/crud/budget/linePayableTerm.py` (estilo legado `db.query`, `db: Session` primero; `get_line_payable_terms_by_line`, `get_line_payable_terms`, `get_line_payable_term_by_id`, `create/update/delete_line_payable_term`), registrado en `app/crud/__init__.py`.

## 6. Expansión en ingesta/creación — pseudocódigo (dentro del builder de egresos)

```
terms_by_line = {}                      # caché local del job: 1 consulta por id_line distinto (evita N+1)
para cada record de egreso fijo elegible (BR-TERM-02):
    id_line = cc.id_line
    if not id_line: emitir_normal(); continue
    if id_line not in terms_by_line:
        terms_by_line[id_line] = crud.get_line_payable_terms_by_line(db, id_line)   # payment_days asc, id asc
    terms = terms_by_line[id_line]
    if not terms: emitir_normal(); continue                      # BR-TERM-10
    if len(terms) == 1 and terms[0].payment_days == 0:
        emitir_una_linea(payment_date=budget_date, monto=monto)  # BR-TERM-03
    else:
        para cada t in terms:
            emitir_cuota(monto * t.payment_pct,
                         payment_date = budget_date + timedelta(t.payment_days))   # BR-TERM-04
```

- El POST manual (`app/api/budget/planning.py`, create-line) reutiliza el MISMO helper (`expand_expense_line(db, cc, fields) -> List[dict]`) en lugar de duplicar el algoritmo.
- Orden determinista de cuotas: `payment_days asc` (primera cuota = la más antigua), desempate `id_line_payable_term asc`. La **línea primaria** devuelta en §7 es la primera de ese orden (D-7).

## 7. Integración con FE-S4D (Editor de líneas)

`POST /budget/planning/{id_budget}/line` cambia `response_model` de `BudgetLine` a **`PlanningLineCreateResult`** = todos los campos de `BudgetLine` (primaria) + `expanded_siblings: List[BudgetLine] = []`:

- Ingreso, gasto no elegible, variable, caso único-0 o Línea sin términos ⇒ `expanded_siblings` VACÍO (contrato idéntico para el consumidor FE-S4D actual: sigue leyendo los campos de `BudgetLine` en el top level — retro-compatible).
- Gasto fijo con N términos ⇒ primaria = primera cuota; `expanded_siblings` = las N−1 restantes.
- PUT/DELETE siguen operando por línea individual (cuota = línea normal; supuesto 9).

## 8. NFR

| ID | Requisito |
|---|---|
| NFR-S5-BE-1 | Cero migraciones manuales: `create_all` levanta la tabla; sin Alembic (convención del repo). |
| NFR-S5-BE-2 | Ingesta: expansión O(#líneas × #términos) en memoria, ≤1 query por Línea distinta (caché `terms_by_line`); sin degradación medible en cargas de 2 000 filas. |
| NFR-S5-BE-3 | Regresión nula garantizada: flag default `False` (BR-TERM-06) + `expanded_siblings` con default `[]` = cero cambios observables para todo lo no-elegible. |
| NFR-S5-BE-4 | Convenciones: camelCase en nombres de archivo, 4 puntos de registro, imports legacy (`import app.crud as crud`), auth espejo de `lineCostRate`. |

## 9. Criterios de aceptación (smoke BE)

- **AC-S5-BE-1:** carga planning de egresos con Línea {30 %/−60, 70 %/0}: fila de $1 000 000 con `budget_date` 2026-03-10 ⇒ DOS líneas: $300 000 `payment_date` 2026-01-09 y $700 000 `payment_date` 2026-03-10; ambas `budget_date` 2026-03-10; Σ causación = $1 000 000.
- **AC-S5-BE-2:** misma fila, Línea sin términos ⇒ UNA línea con el `payment_date` del archivo (BR-TERM-10).
- **AC-S5-BE-3:** términos = [{100 %/0}] ⇒ una línea con `payment_date = budget_date`, monto íntegro (BR-TERM-03).
- **AC-S5-BE-4:** fila variable (tasa) con términos configurados ⇒ NO se explota (BR-TERM-08).
- **AC-S5-BE-5:** `POST /budget/upload/budget-plan-expense` (legacy) con datos que SÍ tienen términos ⇒ resultado idéntico al actual (sin expansión; BR-TERM-06 / AC-REG-01).
- **AC-S5-BE-6:** POST manual `/budget/planning/{id}/line` de gasto fijo elegible ⇒ 201 con `expanded_siblings` (N−1) y N filas persistidas en una sola transacción; forzar error en la 2.ª inserción ⇒ 0 filas (BR-TERM-09).
- **AC-S5-BE-7:** PUT de una cuota no re-explota ni toca hermanas; DELETE borra solo esa cuota; CLON copiado verbatim (mismo N de cuotas, sin multiplicación — BR-TERM-07).
- **AC-S5-BE-8:** CRUD de términos: 201/200/200 ok; POST con `payment_pct: 0` o `1.5` ⇒ 422; PUT id inexistente ⇒ 404 `"LinePayableTerm 999999 not found"`; `by-line` de Línea sin términos ⇒ `[]`.
- **AC-S5-BE-9:** `budget_date` 2026-02-01 con cuota −60 días ⇒ `payment_date` 2025-12-03 persistida; la validación BR-ING-06 del año NO se dispara (solo mira `budget_date`).

## 10. Decision Log (sesión spec-definer 2026-09-14)

| ID | Decisión | Origen |
|---|---|---|
| D-1 | Tabla nueva `line_payable_terms`; NO se reutiliza `line_payment_rules` | Aclaración explícita del stakeholder (esa tabla es de cobro a clientes) |
| D-2 | Sin re-expansión en clone/PUT (evita duplicación multiplicativa) | Refinamiento técnico del supuesto 12, fijado en sesión |
| D-3 | Expansión a nivel de DATOS (no solo visual) | Supuesto 5; espeja ingresos; Vista Flujo/Ejecutiva/Σ ven el desglose sin componentes nuevos |
| D-4 | Caso único-0 mantiene el especial de ingreso (monto íntegro, `payment_date=budget_date`) | Coherencia de motor con BR-ING-05 |
| D-5 | POST manual explota server-side con `expanded_siblings` en la respuesta | Supuesto 8 + integridad del contrato FE-S4D (retro-compatible) |
| D-6 | `payment_pct` se almacena en fracción 0–1 | Mismo semántica que el pct de cobro (multiplicador directo); la UI maneja % (espejo FD-8) |
| D-7 | Primaria = cuota de `payment_days` más antiguo (orden determinista) | Definir qué fila es "la" del 201 sin arbitrariedad |

## 11. Riesgos y PQs

- **R-S5-1:** cuotas que caen fuera del `budget_year` (ej. −60 desde enero) salen del pivote Ene–Dic de Vista Flujo (`monthIndexOf === -1` no puebla celda) ⇒ el efectivo "desaparece" de la vista. Mitigación v2: columna/notice "Fuera de año" (PQ-1). Aceptado v1: hoy ya ocurre con fechas de pago cross-year.
- **R-S5-2:** términos que no suman 100 % ⇒ flujo ≠ causación (BR-TERM-05). Mitigación v2: validación/warning en la pantalla de términos (PQ-2).
- **R-S5-3:** "explosión de cuotas" con Líneas de muchos términos × miles de filas (cuota = línea). Mitigación: el catálogo es por Línea (pocas filas); paginación del Editor ya existe.
- **PQ-1** columna Flujo "fuera de año"; **PQ-2** validación de suma 100 %; **PQ-3** términos por proveedor+Línea; **PQ-4** preview del desdoble en el modal antes de guardar; **PQ-5** agrupar cuotas hermanas (hereda PQ-FD-1 de FE-S4D).

## 12. Checklist de implementación

1. Modelo + registros (2 `__init__`) ⇒ schema + registro ⇒ crud + registro ⇒ api + montaje en `api/budget/__init__.py`.
2. Helper de expansión compartido + flag `expand_payable_terms` en `build_expense_line_records`; call-site planning :136 pasa `True`; legacy sin tocar (:416).
3. `PlanningLineCreateResult` + expansión en POST /line (misma transacción) + orden D-7.
4. Smoke AC-S5-BE-1..9 (escenario real: subir Excel de egresos cuyo CECO tenga Línea con términos; verificar legacy con diff).
5. Congelar contrato ⇒ FE-S5 (`frontend.03_08`).