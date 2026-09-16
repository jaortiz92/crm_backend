# Notas de despliegue — CRM Backend (DDL manual sin Alembic)

El proyecto usa `Base.metadata.create_all`, que **solo crea tablas nuevas**:
nunca añade columnas a tablas existentes y **nunca agrega valores a un tipo
enum existente**. Toda acción de esquema sobre objetos ya creados debe
ejecutarse manualmente (autocommit `psql -c`) **ANTES** de desplegar el
código que la consume. Checklist de deploy: ALTER → deploy.

## 1. Precedente — `budgets.include_carryover` (BE-S6-CARRYOVER, backend.02_16 §3.2)

```sql
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS include_carryover BOOLEAN NOT NULL DEFAULT FALSE;
```

- Columna de preferencia del escenario para el arrastre N−1→N.
- `create_all` no la agrega: sin el ALTER, todo `GET` sobre `budgets` falla
  con `UndefinedColumn` al desplegar el modelo nuevo.

## 2. `linetypeenum` += 'PURCHASE' (BE-S8-BUDGET-PURCHASES, backend.02_18 §3.3)

```sql
ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';
```

- **APLICADO EN DEV el 2026-09-15** vía
  `docker exec db_crm_dev psql -U postgres -d crm -c "ALTER TYPE public.linetypeenum ADD VALUE IF NOT EXISTS 'PURCHASE';"`.
  Verificación: `SELECT unnest(enum_range(NULL::linetypeenum));` ⇒
  `INCOME | EXPENSE | PURCHASE`.
  (Ojo: la verificación literal de la spec usaba `unn(...)` — la función
  correcta de Postgres es `unnest(...)`.)
- El tipo Postgres almacena los **NAMES** de los miembros del enum Python
  (mayúsculas: `'INCOME'`, `'EXPENSE'`, `'PURCHASE'` — evidenced en
  `budget_lines.line_type`); SQLAlchemy resuelve el bind por nombre-then-
  valor, por eso el código filtra con `== "income"` y funciona.
- PG 16: `ADD VALUE` no puede correr dentro de una transacción que luego
  use el valor — usar `psql -c` (autocommit), igual que el precedente.
- Tercer valor de `LineTypeEnum` = línea de COMPRA (importación):
  `budget_date` = fecha de importación, `payment_date` SIEMPRE NULL (las
  cuotas al proveedor se derivan en lectura desde `line_payable_terms`,
  NFR-BE8-1). Todos los consumidores existentes filtran por igualdad
  exacta `'income'`/`'expense'`, así que `purchase` queda fuera
  automáticamente del P&L / cash-flow / listing (spec §3.4); el único
  filtro ciego (`get_carryover_lines`) quedó blindado con el guard
  BR-CO-12.
- **PENDIENTE EN PRODUCCIÓN:** correr el mismo ALTER antes del deploy.
