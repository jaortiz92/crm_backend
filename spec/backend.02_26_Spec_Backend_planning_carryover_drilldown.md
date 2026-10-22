# Spec Backend: Contrato de Soporte para el Drilldown de Detalle de Movimientos de Arrastre

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S15-CARRYDRILL` |
| **Version** | 1.1 -- 2026-10-22 |
| **Base** | BE-S6 (`backend.02_16` carryover) + BE-S7 (`backend.02_17` cuotas COGS de arrastre) + BE-S8 (`backend.02_18` compras de arrastre) + BE-S9 (`backend.02_19` internacion de arrastre). |
| **Contrato** | Autoridad para `frontend.03_23_Spec_frontend_budget_planning_carryover_drilldown.md` (FE-S21). |
| **Componentes** | NINGUNO: cero codigo nuevo. Este spec congela el contrato de datos EXISTENTE que FE-S21 consume. |
| **Dependencias** | Cero. |

> **ENMENDADO v1.1 (2026-10-22) -- solo precision documental, sin cambios de contrato:** verificacion de lectura + smoke en contenedor dev (presupuesto fuente 576, activo, 269 lineas de arrastre para 2027; solo lecturas con rollback) confirma el congelado de la v1.0 con DOS matizaciones redaccionales: (1) el literal exacto de la descripcion del stream de internacion en el codigo es `INTERNMENT_CARRYOVER_DESCRIPTION = "Pago de internaci` + U+00F3 (o con tilde) + `n (arrastre)"` -- el spec decia "internacion" sin tilde; el caracter acentuado es parte del literal de codigo (este spec mantiene texto ASCII y por eso lo escribe por referencia), y (2) `payment_date` es null SOLO en filas materializadas de `origin="line"` que no tengan fecha de pago propia; en filas derivadas (cogs/purchase/internment) SIEMPRE viene poblado cuando hay terminos, y cuando la Linea NO tiene terminos el backend emite UNA cuota al 100 % con `payment_date = budget_date` (anclaje, D-S7-4) -- nunca null. Ninguno de los dos afecta al drilldown FE-S21.

---

## 1. Objetivo

Formalizar que el drilldown de detalle de movimientos de arrastre (FE-S21) se implementa con CERO cambios en el backend: los endpoints y payloads ya existentes son suficientes.

## 2. Contrato congelado (nada de esto cambia)

### 2.1 `GET /budget/planning/{id_budget}/carryover` -> `PlanningCarryoverResult`

```json
{ "enabled": true, "source": { "id_budget": 576, "budget_name": "Prueba 2026 Parcial B", "budget_year": 2026, "status": "active" },
  "lines": [ { "id_budget_line": 881, "id_cost_center": 4, "line_type": "expense",
               "budget_date": "2026-12-20", "payment_date": "2027-01-19",
               "projected_amount": 700000.0, "description": "Importacion dic", "origin": "line" } ],
  "unavailable_reason": null }
```

- `lines[]: PlanningCarryoverLine` con EXACTAMENTE estos atributos: `id_budget_line` (solo presente cuando `origin == "line"`; null en derivados), `id_cost_center`, `line_type` (income|expense|purchase; derivados siempre expense), `budget_date` (anclaje: fecha de la linea fuente SOLO para derivados; fecha propia para material), `payment_date` (fecha efectiva de pago; null cuando no hay terminos), `projected_amount` (monto de la cuota), `description` ("Costo de venta (arrastre)" / "Pago a proveedor (arrastre)" / "Pago de internacion (arrastre)"), `origin` (line|cogs|purchase|internment).
- Orden estable: `coalesce(payment_date, budget_date) ASC`, rank de origen (line:0, cogs:1, purchase:2, internment:3), id null-safe.
- Dinamico (recalcula por request, sin snapshot) BR-CO-04.

### 2.2 Autenticacion y permisos

Sin cambios: quien lea el escenario puede leer el arrastre (patron BE-S6 BR-CO-07). El FE solo lo solicita cuando ya tenga `carryActive` (flag ON y lineas relevantes), y el cache del store queda como fuente unica (sin reintentos).

## 3. Reglas de negocio (para verificacion BE, no implementacion)

- **BR-CD-01:** El FE no requerira endpoints nuevos para el drilldown: solo `GET /{id}/carryover` (cache) + `GET /{id}/detail` + los de motor ya conocidos (payroll/financing/principal-flow para no-activos, y los de simulacion IVA/impuestos con la misma tolerancia 4xx con Promise.allSettled ya implementada en la derivacion de seeds del saldo inicial).
- **BR-CD-02:** Filas de `origin` derivado NO incluyen rastro de `%`/`dias`/id de la linea fuente en la respuesta actual; el drilldown de v1 muestra solo la lista de cuotas (fecha, monto, descripcion, origen). Fase 2 posible (fuera de alcance): enriquecer `PlanningCarryoverLine` con rastro de cuotas (id fuente, pct, terminos).
- **BR-CD-03:** Nada aqui altera `/carryover`, `/initial-balance`, upload, line/cell ni P&G/Ejecutiva. Regresion estructural: cero.

## 4. AC (smoke BE, solo verificacion de contrato)

- **AC-S15-BE-1:** `GET /{id}/carryover` con flag ON y fuente active responde 200 con source + lines + origin correcto; OFF => enabled:false/lines:[]; sin fuente => 200 + "no_source". Regresion de BE-S6/S7/S8/S9 ya salida.
- **AC-S15-BE-2:** El payload `lines` es suficiente para el drilldown: cada fila identifica ceco (id), tipo/origen, fecha efectiva de pago, monto y descripcion; `id_budget_line` presente en filas de material. (Se valido por lectura de `buildCarryPivot` con FE-S21.)

## 5. Checklist

1. Solo verificacion de contrato (lectura + smoke de reglas ya implementadas). Cero archivos de codigo tocados.
2. Congelar contrato => FE-S21 (`frontend.03_23_Spec_frontend_budget_planning_carryover_drilldown.md`).
