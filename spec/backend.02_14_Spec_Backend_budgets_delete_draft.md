# backend.02_14 — Eliminación de presupuestos borrador (DELETE /budget/{id_budget})

**Modulo**: Presupuestos / Planeacion y Escenarios (S4)
**Depende de**: backend.02_12 (planning), backend.02_13 (planning lines)
**Homologo FE**: `crm_frontend/spec/frontend.03_07_Spec_frontend_budget_planning_delete_draft.md`
**Fecha**: 2026-09-14 — **Estado**: Aprobada

## 1. Historia de usuario

> Como usuario quiero que en el dashboard de Planeacion se permitan eliminar los
> presupuestos que son borrador y que nunca han sido utilizados como meta activa.

## 2. Decisiones (supuestos confirmados por el stakeholder)

| ID | Decision |
|----|----------|
| D-1 | Elegibilidad = `status = 'draft'` exclusivamente. `active` (meta vigente) y `closed` (fue meta activa alguna vez) NO son elimrables. `draft` implica "nunca fue meta": no existe transicion de vuelta a draft. |
| D-2 | Borrado FISICO y definitivo: presupuesto + lineas. Sin papelera, sin undo, sin auditoria en v1 (espejo de D-2 de BE-S4D). |
| D-3 | **NO se crea endpoint nuevo**: se modifica el `DELETE /budget/{id_budget}` legacy existente para que aplique la validacion (decision explicita del stakeholder 2026-09-14). El endpoint viejo no tenia guard y podia borrar una meta activa; desde esta spec la validacion aplica a TODOS los consumidores de la ruta (cambio intencional y aceptado). |
| D-4 | Escenarios clonados desde el borrador eliminado SOBREVIVEN: se les pone `parent_budget_id = NULL` (pierden el tooltip "de {padre}", nada mas). |
| D-5 | politica de permiso: solo JWT (cualquier usuario autenticado del modulo), SIN gate de rol. El gate Gerente/Administrador queda reservado para set-target. |

## 3. Contrato — `DELETE /budget/{id_budget}` (ruta existente, sin cambios de URL)

- Auth: JWT (`get_current_user`, ya presente). Sin cuerpo.

| Status | Condicion | Cuerpo |
|--------|-----------|--------|
| 200 | borrador eliminado | `{"message": "Budget deleted successfully"}` (shape EXISTENTE, retrocompatible) |
| 401 | JWT ausente/expirado | estandar FastAPI |
| 404 | presupuesto inexistente | `detail = "Budget {id_budget} not found"` (`Exceptions.register_not_found`, convencion actual) |
| 400 | `status != 'draft'` (active/closed/otros) | `detail = "Only draft budgets can be deleted"` (string plano → FE lo clasifica 'conflict') |
| 500 | fallo no controlado | `detail = "Error deleting budget: {msg}"`, transaccion rollback |

## 4. Reglas de negocio

- **BR-DEL-01** (elegibilidad): elimerable sii `status == 'draft'` (comparacion exacta, server-side, dentro de la misma transaccion). Cualquier otro estado → 400 sin mutacion.
- **BR-DEL-02** (cascada fisica): antes de borrar la fila de `budgets` se eliminan las filas propias que la referencian: `budget_lines.id_budget` y `budget_scenarios.id_budget` (legacy FK NOT NULL).
- **BR-DEL-03** (clones huesped): `UPDATE budgets SET parent_budget_id = NULL WHERE parent_budget_id = :id` en la misma transaccion.
- **BR-DEL-04** (transaccion unica, T-05): UN solo `db.commit()` al final; cualquier excepcion → `db.rollback()`, no queda borrado parcial.
- **BR-DEL-05** (concurrencia): last-write-wins como en el resto del modulo (ASM-7/BR-CEL-03). La ventana entre GET y DELETE se resuelve porque el servidor re-valida el estado al borrar; el FE refresco la lista si llega 400/404.
- **BR-DEL-06** (Base y escenario tratan igual): aplica tanto a Bases (`is_scenario=False`) como a escenarios/clones; se permite dejar un ano sin escenarios.
- **BR-DEL-07** (nombre liberado): al desaparecer la fila, la unicidad (year, name) de BR-ING-04 queda disponible para reuso.

## 5. Implementacion (puntos exactos)

1. `app/crud/budget/budget.py` — modificar `delete_budget(db, id_budget) -> bool` (mismos nombre/firma/retornos):
   - fila inexistente → `False` (el API layer lanza 404; convencion Optional/None actual, no cambia).
   - `db_budget.status != "draft"` → `raise HTTPException(400, "Only draft budgets can be deleted")` (precedente de 400 dentro de CRUD: `commissionRate.py`, `planning.py`).
   - delete masivo `BudgetLine` por `id_budget`, delete masivo `BudgetScenario` por `id_budget` (`.delete(synchronize_session=False)`).
   - `UPDATE` de clones: `parent_budget_id=None` donde `parent_budget_id == id_budget`.
   - `db.delete(db_budget)` → UN `db.commit()` → `True`.
   - Nuevos imports necesarios: `HTTPException, status` (fastapi), modelos `BudgetLine`, `BudgetScenario` desde `app.models.budget`.
2. `app/api/budget/budget.py` — endpoint `delete_budget`: mantener route/dep/mensaje 200; envolver el try/except estandar del modulo (`HTTPException: db.rollback(); raise` / `Exception: db.rollback(); raise 500 "Error deleting budget: ..."`); actualizar docstring citando BR-DEL-01..05.
3. Sin cambios en `schemas`, sin routers nuevos, sin tablas/columnas nuevas.

## 6. Criterios de aceptacion (curl/DB, dev :8003)

- AC-BE-1: DELETE de borrador con lineas → 200 `{"message": "Budget deleted successfully"}`; desaparecen presupuesto + sus `budget_lines` + `budget_scenarios`.
- AC-BE-2: DELETE del `active` del ano → 400 `Only draft budgets can be deleted`; fila intacta.
- AC-BE-3: DELETE de un `closed` → 400; fila intacta.
- AC-BE-4: DELETE id inexistente → 404 `Budget {id} not found`.
- AC-BE-5: DELETE de un padre con clones → 200; clones sobreviven con `parent_budget_id IS NULL`; `GET /budget/planning/` los lista sin `parent_budget_name`.
- AC-BE-6: sin token → 401.
- AC-BE-7: `GET /budget/{id}` del borrado posterior → 404; `GET /budget/planning/{id}/detail` → 404.
- AC-BE-8: `python -m py_compile` limpio y la app importa sin errores (`create_all` no ve FKs huerfanas).

## 7. Fuera de alcance

- Papelera / soft-delete / restauracion / auditoria.
- Borrado masivo por lotes.
- Nuevos roles o permisos granulares.
- Endpoint paralelo en `/budget/planning/*` (prohibido por D-3).
