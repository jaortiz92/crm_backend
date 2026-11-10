# backend.02_27 — Spec Backend: Nómina — Flag "Cotiza pensión" y política fiscal de parafiscales

**Módulo:** `budget.collaborators` (motor de costo laboral) · **Fecha:** 2026-11-10 · **v1.0**

## 1. Resumen

Dos cambios en el módulo de costo laboral de colaboradores (`collaborators` + `LaborCostEngine`):

1. Flag por colaborador **`pays_pension`**: cuando es `False`, el motor **NO emite** el asiento de pensión patronal (`C_PENSION`). La fuente puede ser formulario/API **y la plantilla Excel de nómina** (columna **"Cotiza pension"**).
2. **Política fiscal de parafiscales operativa**: SENA/ICBF/CAJA se liquidan o no según la normativa del país, resuelta **por vigencia anual** con el parámetro existente `aplicacion_parafiscales` (`all | exonerated_lt100 | custom`) y nuevos parámetros `liquidar_sena`, `liquidar_icbf`, `liquidar_caja` para el modo `custom`. `exonerated_lt100` pasa a evaluarse **colaborador a colaborador** (tope 10 SMLV contra el IBC del mes).

## 2. Alcance

**In:** modelo/schema/crud/api del flag; `laborCostEngine.compute_month` (y por extensión `breakdown`, que usa `persist=False` sobre el mismo método); procesador de plantilla (`budgetTemplates.process_budget_plan_collaborators`) y endpoint de importado; recálculo (`POST /recalculate`).
**Out:** deducciones de empleado/neto (el motor no las modela); contratos `service_provision` (emiten solo `C1S`); catálogo `cost_components` (sin cambios); automatización del Decreto 322/2020 (menos de 1 SMLV) — esos casos se cubren manualmente vía flag.

## 3. Cambio de modelo — `app/models/budget/collaborator.py`

```python
# Collaborator
pays_pension = Column(Boolean, nullable=False, server_default="True")
```

**Restricción técnica:** `Base.metadata.create_all` no hace ALTER de tablas existentes: DDL manual ÚNICO (paridad con el ALTER de `budget_lines` de backend.02_21 §4.7/§4.8):

```sql
ALTER TABLE collaborators ADD COLUMN pays_pension BOOLEAN NOT NULL DEFAULT TRUE;
```

Colaboradores existentes quedan `True` (comportamiento actual preservado). Registrar la ALTER en `crm_backend/note.md`.

## 4. Schemas — `app/schemas/budget/collaborator.py` (+ registro en `app/schemas/budget/__init__.py`)

- `CollaboratorCreate`: `pays_pension: bool = True`
- `CollaboratorUpdate`: `pays_pension: Optional[bool] = None`
- `CollaboratorOut`: `pays_pension: bool` (detalle y filas de `CollaboratorListResponse`)

## 5. CRUD — `app/crud/budget/collaborator.py` (+ registro en `app/crud/__init__.py`)

- `create_collaborator`: persistir el flag.
- `update_collaborator_master`: escribir `pays_pension` SOLO cuando el valor es explícito (no None).
- `query_collaborators` / getters: exponer el flag en el Out.

## 6. Motor — `app/services/laborCostEngine.py`

**6.1 Pensión (solo contratos dependientes):** emitir `C_PENSION` **únicamente si** `collab.pays_pension` es True (default True). El flag **no altera** `C_SAL`, `C_SALUD`, `C_ARL`, `C_CAJA`, auxilio de transporte ni provisiones (prima/cesantías/intereses). Contrato `service_provision`: sin cambios (únicamente C1S; pensión/parafiscales no aplican a ese flujo).

**6.2 Matriz de parafiscales (colaborador dependiente, mes M):**

| `aplicacion_parafiscales` | Condición | SENA | ICBF | CAJA |
|---|---|---|---|---p
| `all` | — | sí | sí | sí |
| `exonerated_lt100` | `ibc < 10 * smlv` | no | no | sí |
| `exonerated_lt100` | `ibc >= 10 * smlv` | sí | sí | sí |
| `custom` | según `liquidar_*` (`"1"`/`"0"`) | param | param | param |

- `exonerated_lt100` ahora se evalúa **por colaborador**: CORRECCIÓN del comportamiento actual, que exoneraba globalmente sin medir el salario. El tope (10) se lee del nuevo parámetro `parafiscales_tope_exoneracion_smlv` de la vigencia (falla con `MissingLaborParametersError` si falta, R-05).
- Nuevos parámetros anuales string (D-S11-4) en `labor_cost_parameters` por vigencia: `liquidar_sena`, `liquidar_icbf`, `liquidar_caja` (valores `"1"` / `"0"`). Solo se leen en modo `custom`; faltantes en ese modo => `MissingLaborParametersError` (R-05: el motor no adivina).
- Modos `all` / `exonerated_lt100` IGNORAN las claves `liquidar_*` (pueden coexistir sembradas sin romper nada).
- `C_PENSION` NO se gobierna por `liquidar_*`: lo gobierna `pays_pension` (§6.1).
- ARL/salud: sin cambios. Eliminar el comentario "custom se trata como all (DEP-01)" del motor.
- `is_active=False` del catálogo `cost_components` prevalece sobre cualquier rama (no se emite nada).

## 7. Plantilla Excel + importado

**7.1 Procesador — `budgetTemplates.py`** (columna **"Cotiza pension"**, lookup accent-folded `cotiza_pension`; **NO** en `COLLABORATOR_REQUIRED_COLS`, archivos antiguos importan igual):
- Parseo case-insensitive con trim: SI (con o sin tilde), TRUE, 1, S => `True`; NO, FALSE, 0, N => `False`.
- Valor no reconocido no vacío => motivo de fila: `"Cotiza pension inválida: <raw> (esperado SÍ/NO o vacío)"`; el rechazo all-or-nothing R-06 se mantiene.
- Celda vacía => `None` (no es error; semántica en §7.2).

**7.2 Endpoint de importado (`api/budget/collaborator.py`):**
- ALTA: valor del record; vacío => `True`.
- RE-IMPORT (upsert por `doc_value`, R-07): celda vacía **NO toca** `pays_pension` del master; valor explícito SÍ/NO lo actualiza (vía `update_collaborator_master`).
- Actualizar el docstring de cabecera del procesador (§6) y la guía de columnas de la plantilla de nómina.

## 8. Criterios de Aceptación

- **AC-1** `pays_pension=False` => mes completo SIN líneas `C_PENSION` (SAL/SALUD/ARL/CAJA/provisiones intactas); `breakdown` (`persist=False`) idéntico.
- **AC-2** Excel con "Cotiza pension"=NO => tras importar, 0 líneas C_PENSION del año; con SÍ => idéntico a hoy.
- **AC-3** Vacío en alta => True; vacío en re-import de un master `False` => sigue False (no reset).
- **AC-4** Valor inválido ("CASI") => 400 estructurado con fila + motivo; archivo completo rechazado.
- **AC-5** `exonerated_lt100`: IBC < 10 SMLV => sin SENA/ICBF para ESE colaborador; IBC >= 10 SMLV => con SENA/ICBF; CAJA siempre.
- **AC-6** `custom` + `liquidar_sena="0"` => 0 C_SENA del año; los demás según sus claves.
- **AC-7** `custom` sin claves `liquidar_*` de la vigencia en uso => `MissingLaborParametersError`; importado/recálculo de esa vigencia hace rollback completo (T-05).
- **AC-8** Plantilla sin la columna importa OK (default True / keep).
- **AC-9** El recálculo (R-13) s -emite con las nuevas reglas: cambio de flag o de parámetros actualiza las líneas del año del mes.

## 9. Notas

- Idempotencia R-13 / T-05 / R-06 vigentes; Decimal end-to-end (D-S11-4).
- `liquidar_*` se almacenan como String `"1"`/`"0"` y se parsean a bool en el motor.
- Validación sugerida: smoke test nuevo `crm_backend/test/test_labor_cost_engine_nomin_smoke.py` (estilo de los smokes existentes del repo).