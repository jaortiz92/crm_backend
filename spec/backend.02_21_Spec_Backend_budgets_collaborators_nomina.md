# Spec Backend: Costo total de colaboradores (nómina Colombia) — maestro, parámetros, plantilla de nómina y motor de costo

| Campo | Valor |
|---|---|
| **ID de feature** | `BE-S11-COLLABORATORS` |
| **Spec counterparts** | FE: `frontend.03_15` (FE-S15-COLLAB) — consume los contratos de §9. Bases: BE-S4/BE-S4D (`02_12`/`02_13` — planning y líneas), BE-S8 (`02_18` — patrón de plantilla propia + T-05 todo-o-nada), BE-S10 (`02_20` — patrón lectura/derivación) |
| **Tablas nuevas** | 6: `collaborators`, `collaborator_salary_plans`, `labor_cost_parameters`, `labor_arl_rates`, `cost_components`, `collaborator_provision_accruals` |
| **DDL requerido** | 3 ALTER manuales sobre `budget_lines` + seeds (ver §4.8 — despliegue en 3 fases; `create_all` NUNCA agrega columnas a tablas existentes; precedente documentado: `include_carryover`) |
| **Convenciones** | T-03 legacy `db.query`, T-05 un solo commit, camelCase filenames, registro de submódulos budget (`models/budget/__init__.py`, `schemas/budget/__init__.py` con imports nombrados, `crud/budget/__init__.py` con `from .x import *`, `api/budget/__init__.py` con `include_router`; **`app/main.py` intocado**), plantilla Excel con `skiprows=7` |
| **Fecha** | 2026-09-23 |

---

## 1. Problema y modelo conceptual

Hoy el costo de colaboradores entra como **un valor único manual** dentro del gasto (fila de `budget_lines` expense o ingesta contable). Bajo la legislación laboral colombiana, detrás del salario básico hay componentes que **se pagan cada mes** y otros que **se causan hoy y se pagan a futuro**. Este módulo elimina el número manual: el usuario registra identifications y salarios (maestro o plantilla de nómina) y el sistema deriva el costo total.

```
Colaborador (maestro, 1 centro de costo)
 └─ PlanSalarial (vigencias: salario, asignaturas, integral)
     └─ MOTOR laborCostEngine (usa labor_cost_parameters de la vigencia)
         ├─ capa CAJA (mensual, fecha pago = dia_pago_salario):
         │    SAL salario+asig.salarial · TRA auxilio transporte ·
         │    SALUD 8.5% · PENSIÓN 12% · ARL clase I–V · CAJA 4% · SENA 2% · ICBF 3%
         ├─ capa PROVISION (causa mensual en accruals; asientos con fecha de pago legal):
         │    PRIMA 1/12 (base ≤2 SMLV) paga 30/06 y 20/12 ·
         │    CESANTÍAS 1/12 consigna ≤14/02 año sig ·
         │    INTERESES 12%/año (1% mensual) paga ≤31/01 año sig
         ├─ prestación de servicios: SOLO honorarios (C1S), sin seg. social ni prestaciones
         └─ término (liquidación): saldo provisiones + parte del mes, fecha pago = fecha término
 └─ materializa budget_lines (line_type=expense, behavior_type=fixed,
        source_engine='collaborator_cost'|'collaborator_liquidation',
        id_collaborator + cost_component_code poblados)
REAL: intocado — ActualExpense/ActualCost siguen ingiriéndose de SIIGO (D-S11-6)
```

## 2. Alcance

**Incluye:** (1) maestro de colaboradores con planes salariales historizados por vigencia; (2) parámetros laborales anuales configurables + tabla ARL por clase de riesgo; (3) catálogo de componentes con capa CAJA/PROVISION (sembrado, 2 extralegales inactivos); (4) motor de cálculo mensual con prorrateo por ingreso/término; (5) plantilla Excel separada "Solicitud Presupuesto Nómina/Colaboradores" con import todo-o-nada y upsert; (6) generación/idempotencia de `budget_lines` (solo toca filas del motor); (7) liquidación automática al terminar contrato; (8) endpoints de breakdown, provisions y recálculo.
**Excluye (v1):** liquidación de nómina con deducciones al empleado (queda en SIIGO); horas extra/recargos/primas variables/asignaciones intermitentes; reparto de un colaborador entre varios CECO; recálculo retroactivo de gasto real o proyecciones históricas manuales; incapacidades/licencias/vacaciones como eventos; compensatorio vacacional activo (componente sembrado OFF); monedas ≠ COP; analítica agregada "costo anual por CECO" (OQ-02, ver `frontend.03_15` §9).

## 3. Registro de decisiones

### 3.1 Sesión stakeholder 2026-09-23 (origen: spec consolidada del feature)

| ID | Decisión (era suposición #n) |
|---|---|
| A-01 | El monto único manual se reemplaza por cálculo del sistema; el usuario solo captura el salario |
| A-02 | SMLV, auxilio de transporte y topes = parámetros por vigencia anual; cero hardcode |
| A-03/14 | Contratos dependientes con prestaciones completas; prestación de servicios con costo reducido (solo honorarios) |
| A-04 | Dos capas: pagos inmediatos vs. provisiones causadas con pago en fecha legal |
| A-05 | El CRM NO liquida nómina; solo costo patronal estimado/proyectado |
| A-06 | Prestaciones sobre salario + asignaciones salariales, con topes legales |
| A-07 | Sin horas extra/recargos/bonificaciones variables en v1 |
| A-08 | Resultado como `BudgetLine` expense mensual por CECO; flujo presupuesto-vs-real intacto |
| A-09 | Un CECO por colaborador (sin reparto %) |
| A-10 | Cero recálculo retroactivo de datos pre-existentes |
| A-11 | Tarifas default = ley colombiana vigente, editables por admin (extralegales configurables) |
| A-12 | Todo COP, español, dentro de la app actual |
| **A-13** | **Plantilla separada de nómina (Opción 3)** — no se muta el formato SIIGO de gastos, no es solo-UI: endpoint + processor + validación propios |

### 3.2 Decisiones técnicas

| ID | Decisión |
|---|---|
| D-S11-1 | Plantilla propia con layout "propio simple" estilo §5.4 de compras: hoja 1, fila 8 encabezado (`skiprows=7`), fila 9 datos. El formato SIIGO de gastos permanece intacto (A-13) |
| D-S11-2 | Enums de bajo cardinalidad (`contract_type`, `status`, `layer`, doc_type) como `String + Literal` de pydantic, **sin tipos enum de Postgres** — precedente doloroso: `linetypeenum` exige ALTER manual; aquí las tablas son nuevas y no queremos repetir eso |
| D-S11-3 | Las provisiones se **acumulan** en `collaborator_provision_accruals`; el asiento de pago = `causado_acumulado − pagado` (un semestre/prima siempre cuadra a 0; jamás se recalcula el pago desde la tarifa) |
| D-S11-4 | `Numeric(15,2)` + `Decimal` en todo el camino de dinero; tarifas `DECIMAL(9,6)`; prohibido `Float` (el `amount Float` de ActualCost NO es modelo a imitar) |
| D-S11-5 | Vínculo motor↔línea por 3 columnas nuevas **nullable** en `budget_lines` (`id_collaborator`, `cost_component_code`, `source_engine`): NULL en todas las filas existentes ⇒ 100% retrocompatible; el reemplazo idempotente solo toca filas con `source_engine LIKE 'collaborator_%'` |
| D-S11-6 | Lado real sin cambios: la comparación presupuesto-vs-real (P&L, flujo, ejecutiva) no se toca; el motor solo escribe proyección |
| D-S11-7 | Salario = dato confidencial (Ley 1581 de 2012). Allow-list por `role_name` vía settings (`COLLAB_VIEW_ROLES`, `COLLAB_EDIT_ROLES`); usuarios sin permiso reciben maestro con salario `null` + `salary_masked: true` |
| D-S11-8 | Ventana de proyección: desde el mes de carga (o `valid_from` del plan, si es posterior) hasta el 31/12 del `budget_year` del escenario activo y nunca después de `termination_date` |
| D-S11-9 | Cero parámetros para la vigencia requerida ⇒ error estructurado 400 (R-05): el motor no adivina tasas |

## 4. Modelo de datos

### 4.1 `collaborators` (tabla nueva, `app/models/budget/collaborator.py`)

```
id_collaborator        Integer PK
doc_type               String(4)   NOT NULL default 'CC'      -- CC | CE | NIT
doc_value              String(20)  NOT NULL UNIQUE            -- clave natural del upsert
full_name              String(150) NOT NULL
id_cost_center         Integer FK cost_centers NOT NULL       -- 1 CECO (A-09)
contract_type          String(30)  NOT NULL                   -- D-S11-2
status                 String(12)  NOT NULL default 'active'  -- active | terminated
hire_date              Date        NOT NULL
termination_date       Date        NULL
risk_class             String(1)   NULL                       -- I..V; NULL => arl_default_class
id_collection          Integer FK product_collections NULL    -- temporada default (NULL ok)
notes                  Text        NULL
created_at/updated_at  DateTime
```

### 4.2 `collaborator_salary_plans`

```
id_salary_plan PK · id_collaborator FK NOT NULL
salary                 Numeric(15,2) NOT NULL CHECK > 0     -- honorarios en servicio
allowance_salary       Numeric(15,2) NOT NULL default 0     -- asignación salarial fija
allowance_non_salary   Numeric(15,2) NOT NULL default 0     -- no salarial: no IBC, no base prestaciones
is_integral            Boolean NOT NULL default False
valid_from             Date NOT NULL · valid_to Date NULL   -- NULL = abierto (BR-COLLAB-02)
created_at
UNIQUE(id_collaborator, valid_from)
```

### 4.3 `labor_cost_parameters` — clave/valor por vigencia anual

```
id PK · vigencia Integer NOT NULL · key String(60) NOT NULL · value String(60) NOT NULL
UNIQUE(vigencia, key)
```

| key | Significado | default 2026 (⚠ ficticios, validar DEP-01) |
|---|---|---|
| `smlv` | SMLV COP mes | 1.500.000,00 |
| `aux_transporte_valor` | auxilio mensual fijo | 150.000,00 |
| `aux_transporte_tope_smlv` | tope salario para auxilio | 2 |
| `salud_patronal_pct` | EPS patronal | 0.085000 |
| `pension_pct` | pensión patronal | 0.120000 |
| `caja_pct` | Caja de Compensación | 0.040000 |
| `caja_tope_smlv` | base caja ≤ N SMLV | 2 |
| `sena_pct` / `icbf_pct` | parafiscales | 0.020000 / 0.030000 |
| `aplicacion_parafiscales` | `all` \| `exonerated_lt100` \| `custom` | **a confirmar (DEP-01)** |
| `prima_tasa` | causación mensual prima | 0.083333 |
| `prima_tope_smlv_base` | base prima ≤ N SMLV/mes | 2 |
| `cesantias_tasa` | causación mensual cesantías | 0.083333 |
| `intereses_cesantias_anual` | 12 % legal | 0.120000 |
| `integral_ibc_factor` | IBC = total × factor | 0.700000 |
| `integral_tope_smlv` | tope IBC integral | 25 |
| `dia_pago_salario` | `last_business_day` \| día del mes | last_business_day |
| `dia_pago_servicios` | fecha pago honorarios | last_business_day |
| `fecha_prima_1` / `fecha_prima_2` | 30/06 · 20/12 | MM-DD |
| `fecha_intereses` / `fecha_cesantias` | 31/01 · 14/02 (año siguiente) | MM-DD |
| `arl_default_class` | clase cuando collaborator.risk_class NULL | I |

### 4.4 `labor_arl_rates`

```
id PK · vigencia Int · risk_class String(1) · rate DECIMAL(9,6)   UNIQUE(vigencia, risk_class)
defaults res./Min.: I 0.00522 · II 0.01044 · III 0.02436 · IV 0.04350 · V 0.06960 (⚠ DEP-01)
```

### 4.5 `cost_components` — catálogo (sembrado; lectura = `GET /budget/cost-components`)

```
code PK-id · code String(12) UNIQUE · name String(80) · layer String(12) CAJA|PROVISION
formula_key String(40) · is_legal Boolean · is_active Boolean · payment_date_key String(40) NULL
```

`SAL, C1S, TRA, SALUD, PENSION, ARL, CAJA, SENA, ICBF` (CAJA, legales) · `PRIMA, CESANTIAS, INTERESES` (PROVISION, legales, `payment_date_key` → fecha prima 1/2, intereses, cesantías) · `LIQ` (PROVISION, liquidación) · `PRE_EXTRALEGAL`, `VAC_COMPENSATORIO` (PROVISION, **is_active=False** — A-11/R-12).

### 4.6 `collaborator_provision_accruals`

```
id PK · id_collaborator FK · component_code FK cost_components · period_month Date (1er día)
accrued Numeric(15,2) NOT NULL · paid Numeric(15,2) NOT NULL default 0 · params_vigencia Int
UNIQUE(id_collaborator, component_code, period_month)
```

### 4.7 Extensión `budget_lines` (columnas nuevas NULLABLEs — D-S11-5)

`id_collaborator Integer NULL` (sin FK de BD para no depender del orden; integridad por motor) · `cost_component_code String(12) NULL` · `source_engine String(40) NULL`. Modelos/schemas: `app/models/budget/budgetLine.py` y `app/schemas/budget/budgetLine.py` reciben los 3 campos como optionals (`None` por defecto) sin alterar contratos existentes.

### 4.8 Despliegue (3 fases — documentar en `crm_backend/note.md`)

1. **Fase 1 — código:** subir; `Base.metadata.create_all` crea las 6 tablas nuevas.
2. **Fase 2 — ALTER manual** (`create_all` no agrega columnas; `psql -c` autocommit, dev: `docker exec db_crm_dev psql -U postgres -d crm -c "..."`):

```sql
ALTER TABLE budget_lines
  ADD COLUMN IF NOT EXISTS id_collaborator    integer,
  ADD COLUMN IF NOT EXISTS cost_component_code varchar(12),
  ADD COLUMN IF NOT EXISTS source_engine       varchar(40);
```

3. **Fase 3 — seeds idempotentes** (`app/utils/seeds/laborCostSeed.py`, natural key): 15+2 componentes, `labor_arl_rates` y `labor_cost_parameters` de la vigencia 2026 **con valores validados por contabilidad** (DEP-01; NUNCA sembrar los ficticios de este doc en prod).

## 5. Fórmulas del motor (`app/services/budget/laborCostEngine.py` — puro, sin HTTP, inyectable para test)

Entrada: `id_collaborator, mes(Año-Mo)` → salida: `list[Asiento]` con `(componente, capa, monto, budget_date, payment_date, vigencia_params)`. Todo `Decimal`, `ROUND_HALF_UP`, 2 dec. solo por asiento (NFR-04).

### 5.1 Bases (mensuales, sobre el plan vigente ese mes)

```
IBC        = salario + allowance_salary            (asign. no salarial JAMÁS entra)
             integral: IBC = min(total_plan × integral_ibc_factor, integral_tope_smlv × smlv)
base_prima = min(IBC, prima_tope_smlv_base × smlv)
base_ces   = IBC                                   (cesantías sin tope legal por defecto)
base_caja  = min(IBC, caja_tope_smlv × smlv)
factor_prorrateo = días_causados_mes / días_calendario_mes   (BR-CALC-06: ingreso/término en meses parciales; 1.0 si mes completo)
```

### 5.2 Capa CAJA (contratos dependientes) — 1 asiento/componente/mes, `budget_date` = fin de mes, `payment_date` = `dia_pago_salario` del mes

| Cód | Fórmula mensual |
|---|---|
| SAL | `(salario + allowance_salary) × factor_prorrateo` |
| TRA | `aux_transporte_valor × factor_prorrateo` **solo si** `(salario + allowance_salary) ≤ aux_transporte_tope_smlv × smlv`; nunca base de prestaciones |
| SALUD | `IBC × salud_patronal_pct` |
| PENSION | `IBC × pension_pct` |
| ARL | `IBC × labor_arl_rates[risk_class or default]` |
| CAJA | `base_caja × caja_pct` (según `aplicacion_parafiscales`) |
| SENA | `IBC × sena_pct` (si aplica) |
| ICBF | `IBC × icbf_pct` (si aplica) |

### 5.3 Capa PROVISION — causación mensual a `collaborator_provision_accruals` + asientos de pago SOLO en los meses legales

| Cód | Causación (mes) | Asiento de pago |
|---|---|---|
| PRIMA | `base_prima × prima_tasa × factor_prorrateo` | mayo→jun (mes jun, `payment_date=fecha_prima_1`): `Σcausado ene–jun − Σpagado`; jul–dic: `Σcausado jul–dic − Σpagado` (`fecha_prima_2`) |
| CESANTIAS | `base_ces × cesantias_tasa × factor_prorrateo` | feb año N+1 (`fecha_cesantias`): saldo `Σcausado año N − Σpagado` |
| INTERESES | `base_ces × intereses_cesantias_anual / 12 × factor_prorrateo` | ene año N+1 (`fecha_intereses`): saldo año N |

Reglas: el asiento de pago NO se genera en el mes de causación; el último pago del periodo cierra el saldo exactamente a 0 (D-S11-3); `paid` solo lo marca el motor (no hay pago real en CRM). Si el colaborador termina, el saldo pendiente pasa a LIQ (§5.5).

### 5.4 Prestación de servicios (A-14)

Un único asiento `C1S` "Honorarios" capa CAJA, monto = salario × factor_prorrateo, `payment_date` = `dia_pago_servicios`; cero seg. social, cero parafiscales, cero provisiones.

### 5.5 Liquidación por término (BR-LIQ-01)

Al pasar a `terminated` (UI, endpoint o `Fecha de Terminación` de la plantilla), el mes del término produce: prorrateo CAJA de días trabajados + saldo PRIMA + saldo CESANTIAS + saldo INTERESES como asientos `LIQ` (capa PROVISION, `payment_date = termination_date`), `source_engine='collaborator_liquidation'`; meses > término: cero asientos (R-11).

### 5.6 Ejemplo ilustrativo — ⚠ parámetros FICTICIOS, no son norma

SMLV 1.500.000 · aux 150.000 · salario 2.000.000 sin asignaciones · clase I · mes completo 2026-03:
CAJA: SAL 2.000.000 · TRA 150.000 · SALUD 170.000 · PENSIÓN 240.000 · ARL 10.440 · CAJA 80.000 · SENA 40.000 · ICBF 60.000 = **2.750.440,00**
PROVISION (causa): PRIMA 166.666,67 · CESANTIAS 166.666,67 · INTERESES 20.000,00 = **353.333,34** → costo total del mes **3.103.773,34**. Pagos: 30/06 prima ene–jun = 1.000.000,02 (cierra a 0 con el asiento, no con fórmula); 31/01/2027 intereses; 14/02/2027 cesantías.

## 6. Plantilla "Formato Solicitud Presupuesto Nómina/Colaboradores.xlsx" + processor (A-13)

Método `process_budget_plan_collaborators` en `app/utils/templates/budgetTemplates.py` (misma familia que `process_budget_plan_purchase`): hoja 1, `skiprows=7` (encabezado fila 8, datos fila 9), `_clean_column_names()`.

| Columna Excel | Req | Mapeo/validación |
|---|---|---|
| `Documento` | ✔ | `doc_value`; vacío ⇒ fila inválida; duplicado en el mismo archivo ⇒ fila inválida |
| `Tipo Documento` | ✔ | CC/CE/NIT (case-insensitive); default CC si vacío |
| `Nombres y Apellidos` | ✔ | no vacío |
| `Tipo de Contrato` | ✔ | mapa estricto: "Término indefinido"→`open_ended`, "Término fijo"→`fixed_term`, "Obra o labor"→`work_or_service`, "Prestación de servicios"→`service_provision`; valor desconocido ⇒ fila inválida |
| `Salario Básico Mensual` | ✔ | numérico COP > 0 (igual que `monto` en compras) |
| `Centro de Costo` | ✔ | **primer token** del código (regla idéntica a income/purchase); desconocido ⇒ fila inválida |
| `Fecha de Ingreso` | opt | dd/mm/yyyy (helper `_parse_import_date` de compras, reutilizado); default = primer día de la ventana |
| `Fecha de Terminación` | opt | fecha ≤ hoy ⇒ status terminated + liquidación; futura ⇒ programada (v1: se guarda, motor la aplica desde ese mes) |
| `Fecha de Aumento Salarial` | opt | `valid_from` del plan; default = hoy; si existe plan abierto, se cierra el anterior (`valid_to = valid_from − 1`) |
| `Asignación Salarial Fija` / `Asignación No Salarial` | opt | numérico ≥ 0, default 0 |
| `Clase de Riesgo ARL` | opt | I–V; NULL ⇒ `arl_default_class` |
| `Temporada` | opt | `get_collection_by_short_name`; desconocida ⇒ `id_collection` NULL (paridad compras A-01) |
| `Observaciones` | opt | Text |

Reglas de ingesta: **R-06** todo-o-nada (T-05) con 400 `{message, invalid_rows:[{excel_row, motivo}]}` (fila Excel = df index + 9); **R-07 upsert** por `doc_value`: inexistente ⇒ alta colaborador+plan; existente con salario/vigencia distintos ⇒ nuevo plan (BR-COLLAB-02); idéntico ⇒ no-op (contador `no_change`); **R-08** el archivo NUNCA lleva costos totales/provisiones — solo salarios (el desglose lo hace el motor); **R-09** al confirmar (un solo commit, T-05) se ejecuta el motor e R-13 (reemplazo idempotente) para la ventana §D-S11-8 de los colaboradores del archivo.

## 7. Materialización en `budget_lines` + idempotencia (A-08)

| Campo BudgetLine | Valor del motor |
|---|---|
| `line_type` / `behavior_type` | `expense` / `fixed` |
| `id_cost_center` | CECO del colaborador |
| `budget_date` | último día del mes de causación (capa CAJA) / mes del asiento PROVISION |
| `payment_date` | fecha de pago proyectada (§5.2/§5.3/§5.5) |
| `projected_amount` | monto del asiento |
| `description` | `"{Componente} — {full_name} ({doc_value})"` |
| `id_collection` | temporada del colaborador (NULL si no aplica) |
| `id_collaborator` / `cost_component_code` / `source_engine` | poblados (D-S11-5); `source_engine ∈ {collaborator_cost, collaborator_liquidation}` |

**R-13 (idempotencia):** el reemplazo borra/regenera ÚNICAMENTE `WHERE source_engine LIKE 'collaborator_%' AND id_collaborator = X AND mes affected` — líneas manuales, de otras plantillas o reales conviven intactas (invariante verificable). Cambios de parámetros recalculan solo meses ≥ nueva vigencia. `POST /budget/collaborator/recalculate` reejecuta el motor sobre meses del año del escenario.

## 8. Cambios por archivo

| Punto (checklist budget-submodule) | Archivo |
|---|---|
| Model | `app/models/budget/collaborator.py` (6 clases) → `app/models/budget/__init__.py` |
| Model (extensión) | `app/models/budget/budgetLine.py` + 3 columnas nullable (§4.7) |
| Schemas | `app/schemas/budget/collaborator.py` (Colaborator/SalaryPlan/LaborParameter/CostComponent/BreakdownOut/CollabImportResult/RecalcRequest…) → `app/schemas/budget/__init__.py` (imports nombrados) |
| CRUD | `app/crud/budget/collaborator.py` (query legacy, `Session` 1er arg) → `app/crud/budget/__init__.py` (`from .collaborator import *`) |
| API | `app/api/budget/collaborator.py` (router `collaborator` + `labor_params` + `cost_components`) → `app/api/budget/__init__.py`: `prefix="/collaborator"`, `prefix="/labor-params"`, `prefix="/cost-components"`; **`app/main.py` no se toca** (budget ya está incluido) |
| Servicios | `app/services/budget/laborCostEngine.py` (puro) |
| Templates | `app/utils/templates/budgetTemplates.py` += `process_budget_plan_collaborators` + `COLLABORATOR_REQUIRED_COLS` |
| Seeds | `app/utils/seeds/laborCostSeed.py` (nuevo directorio o `app/utils/` — fase 3 §4.8) |
| Settings | `app/settings.py` += `COLLAB_VIEW_ROLES: list[str]`, `COLLAB_EDIT_ROLES: list[str]` (`.env`) |

## 9. Contrato API (JWT `get_current_user`; errores estilo `Exceptions`)

```
POST   /budget/collaborator/import                 multipart file → 200 {imported,created,updated,no_change,generated_lines} | 400 {message,invalid_rows}
GET    /budget/collaborator                        ?q=&id_cost_center=&status=&page=&size= → {total,items[]}  (salario null+salary_masked si sin permiso)
POST   /budget/collaborator                        create manual → 409 doc_value duplicado | 403 sin permiso
GET    /budget/collaborator/{id}
PUT    /budget/collaborator/{id}                   campos maestro (NO salario)
POST   /budget/collaborator/{id}/salary-plan       {salary, allowance_salary?, allowance_non_salary?, is_integral?, valid_from} → cierra plan anterior (BR-COLLAB-02)
POST   /budget/collaborator/{id}/terminate         {termination_date} → status terminated + asientos LIQ (5.5)
GET    /budget/collaborator/{id}/breakdown?month=2026-09   → {month, components:[{code,name,layer,amount,payment_date}], total_caja, total_provision, params_vigencia}
GET    /budget/collaborator/{id}/provisions        → {balances:[{component_code, accrued, paid, balance}]}
POST   /budget/collaborator/recalculate            {month, id_collaborator?|id_cost_center?} → {replaced_lines}
GET    /budget/labor-params?vigencia=2026          catálogo clave/valor + arl_rates (admin)
PUT    /budget/labor-params                        {vigencia, values:{key:value…}} upsert (admin; R-05)
GET    /budget/cost-components                     catálogo lectura (los inactivos se ocultan en UI)
```

Roles (D-S11-7): GETs con breakdown/salary-plan/params → `role_name ∈ COLLAB_VIEW_ROLES`; import/create/update/terminate/recalculate/params-PUT → `COLLAB_EDIT_ROLES`. 403 con `detail` legible.

## 10. Reglas de negocio (ids consolidados con R-nn de la spec de sesión)

BR-COLLAB-01 = R-08 (la captura humana es SOLO salario/datos, jamás el costo total). BR-02 = R-01 (plan vigente único; aumentos crean vigencia, no editan cerrado). BR-03 = R-05 (vigencia sin parámetros ⇒ 400). BR-04 = R-06 (import todo-o-nada). BR-05 = R-07 (upsert idempotente por documento). BR-06 = R-10/D-S11-4 (Decimal end-to-end, ±0.01 por asiento). BR-07 = R-11 (sin días causados ⇒ cero asientos). BR-08 = R-12 (extralegales OFF por default). BR-09 = R-13 (reemplazo solo `collaborator_*`). BR-10 = §5.3/D-S11-3 (pago = acumulado−pagado, cierre exacto). BR-11 = §5.1 (no salarial jamás en IBC/bases). BR-12 = BR-CALC-06 prorrateo calendar días. BR-13 = D-S11-6 (lado real intocado). BR-14 = D-S11-7 (mascaramiento salarial). BR-15 = R-09 (import ⇒ regeneración de ventana en el mismo commit).

## 11. NFR

| ID | Requisito |
|---|---|
| NFR-01 | Import 500 colaboradores × 12 meses < 3 s; breakdown < 100 ms; una transacción por import (T-05) |
| NFR-02 | Ley 1581/2012: salary confidencial (§9); sin export masivo de salarios; logs de import/edición con usuario |
| NFR-03 | Toda línea guarda `params_vigencia` de hecho reproducible; salary_plans y params: UPDATE solo vía endpoints auditados, nunca DELETE de históricos |
| NFR-04 | Cero `float` en dinero del motor; `Numeric(15,2)`/`DECIMAL(9,6)`; cuantización `ROUND_HALF_UP` |
| NFR-05 | Plantillas income/expense/purchase y ETLs reales sin cambios de comportamiento; `source_engine` nullable |
| NFR-06 | Año laboral nuevo = crear vigencia (NFR-07) sin tocar código |

## 12. Criterios de aceptación (G/W/T)

AC-CFG-1 (BR-03): vigencia sin parámetros → 400 con mensaje de vigencia faltante, 0 líneas. AC-PLT-1 (BR-04): una fila sin `Centro de Costo` → 400 `invalid_rows[0].excel_row` = fila real, 0 altas (todo-o-nada). AC-PLT-2 (BR-05/BR-01): segunda importación del mismo archivo → `no_change=5, generated_lines` idéntico en total; ninguna celda de costo total fue requerida. AC-CALC-1: salario 2.000.000 > tope auxilio (2×SMLV 1.500.000=3.000.000 → SÍ aplica; caso 3.500.000 → TRA=0). AC-CALC-2 (tope prima): IBC 6.000.000 → base_prima 3.000.000 → PRIMA mes = 250.000. AC-CALC-3 (integral): total 30.000.000 → IBC = min(21.000.000, 25×SMLV). AC-CALC-4 (capa): en un mes de causación NO hay asientos PRIMA/CESANTIAS/INTERESES con payment_date ≠ fin de mes; los semestrales/anuales aparecen solo en 30/06, 20/12, 31/01, 14/02. AC-SVC-1 (A-14): service_provision ⇒ exactamente 1 asiento C1S/mes, 0 provisiones. AC-INT-1 (BR-09): reimportar 2× no duplica líneas; líneas manuales del mismo CECO intactas. AC-INT-2: breakdown de un mes cuadra: Σ CAJA + Σ PROVISION = Σ budget_lines del motor del colaborador en el año. AC-LIQ-1: término 31/03 con prima ene–mar causada → asiento LIQ prima `payment_date=31/03`; abril→cero asientos; `paid` de PRIMA = accrued (saldo 0). AC-DEP-1: fases §4.8 aplicadas en dev → `source_engine` poblado, seed 2026 presente. AC-SEG-1 (NFR-02): rol fuera de `COLLAB_VIEW_ROLES` → breakdown 403 y maestro con `salary_masked:true`.

**Verificación:** sin suite de tests en el repo → (1) `laborCostEngine` es puro: mínimo un `pytest tests/test_laborCostEngine.py` con los ejemplos de §5.6/AC-CALC* (recomendado go-live), (2) plantillas reales en dev :8003, (3) taller de cuadre con contabilidad: 3 nóminas reales vs. breakdown, tolerancia ≤ 0.5 % por componente.

## 13. Dependencias / riesgos / abiertos

| ID | Ítem | Acción |
|---|---|---|
| DEP-01 | **Tarifas/topes reales vigentes** (SMLV 2026, valor auxilio, tabla ARL, exoneraciones parafiscales Ley 2155/2021 por tamaño de empresa) | BLOQUEANTE go-live: contabilidad confirma antes de la Fase 3 (§4.8) |
| DEP-02 | Plan de cuentas SIIGO del real: match fino real↔proyección solo mejora si nómina se registra por cuenta/componente | Si no, comparación queda a nivel "Nómina" consolidada (aceptado A-08) |
| RSK-01 | Deriva normativa anual | NFR-06; riesgo residual = admin que no crea la vigencia → R-05 la hace explícita |
| RSK-02 | Confidencialidad salarial | D-S11-7; falta revisar aviso/consentimiento con jurídico (OQ-BE-2) |
| OQ-BE-1 | Fechas reales de pago internos (último hábil vs día fijo; auxilio ¿pago o consignación?) | Parámetros listos; confirmar con admin |
| OQ-BE-2 | Nombres exactos de `role_name` para allow-list | Definir al implementar; defaults en `.env` |

## 14. Trazabilidad

Requisito→código: A-13→§6+§8(processor+endpoint); A-01/A-08→§7; A-02/A-11→§4.3/4.4; A-03/14→§5.4; A-04→§5.2/5.3; A-06→§5.1; A-07→§2 excluye; A-09→§4.1; A-10→§7 parr. 2; A-05/A-12→§2/NFR. AC→sección: cada AC cita su BR en §10/§12. Contraparte FE: `frontend.03_15` §4 consume §9 de esta spec.

---

## 15. ENMIENDA A-2026-09-28 (Opción C + A) — materialización automática y banner de estado

Contexto stakeholder: la carga de nómina vive en `CollaboratorsView` (A-13) y el
upload center del escenario (ingresos/gastos/compras) no tiene cuarto slot; al
importar nómina **antes** de existir presupuesto activo del año, `run_projection`
persistía maestro+causaciones pero dejaba los asientos sin materializar (l.802 de
la enmienda original: `no active scenario`). Esta enmienda elimina la trampa del
orden de carga y da descubribilidad.

| ID | Decisión |
|---|---|
| D-S11-10 | **Gancho Opción C**: `PUT /budget/planning/{id}/set-target` (única autoridad de activación, BR-TGT-01) ejecuta `materialize_for_scenario_year(db, budget_year)` DESPUÉS del commit de activación, sobre TODOS los colaboradores `active` con plan: ventana enero→31/12 del año de la meta vía `resolve_window(c, 01-01)` + `run_projection` (R-13 idempotente: meses ya proyectados se reemplazan con iguales; líneas manuales/otras plantillas/real intactos). El hook NUNCA falla la activación: errores de nómina (R-05 sin vigencia, rollback del hook) degradan a `payroll_warnings[]` en la respuesta; la activación vive en su propia transacción. El set-target idempotente (ya era meta) TAMBIÉN re-proyecta — reclick sirve de retry manual. |
| D-S11-11 | **Endpoint Opción A**: `GET /budget/collaborator/materialization-status?year=` → `MaterializationStatusOut` (`year`, `scenario_id_budget`, `active_collaborators`, `collaborators_with_open_plan`, `payroll_lines_in_scenario`, `needs_materialization`). Solo conteos agregados (cero salarios/nombres/montos): puerta de auth simple, no `COLLAB_VIEW_ROLES` (D-S11-7 protege datos económicos, no advertencias). Ruta registrada ANTES de `/{id_collaborator}` (literal primero). |
| D-S11-12 | `PlanningSetTargetResult` gana `payroll_lines_created: Optional[int]` y `payroll_warnings: List[str] = []` — aditivos con default (consumidores FE/S8/S14 no cambian; None = backend pre-enmienda). |


| D-S11-13 | GOTCHA de montaje corregido en QA (2026-09-28): las rutas de coleccion de nomina se registran con path `""` (`GET/POST /budget/collaborator` SIN slash, convencion del repo: cost-center/actual-cost usan igual `/budget/x` sin slash) Y el include de los 3 sub-routers viaja ANTES de `budget_router` en `api/budget/__init__.py`. Razon: el `GET /budget/{id_budget}` legacy captura cualquier segmento literal de 2 partes (422 int_parsing input='collaborator' - reproducido en dev). Starlette resuelve en orden de registro; cualquier sub-module nuevo de /budget con ruta de 2 partes debe respetar esta precedencia. |

Archivos tocados: `app/services/laborCostEngine.py` (+`materialize_for_scenario_year`),
`app/crud/budget/collaborator.py` (+`list_active_collaborators`, `count_active_collaborators`,
`count_collaborators_with_open_plan`, `count_engine_lines_for_budget` — este último usa la
MESMA propiedad `ENGINE_SOURCE_PATTERN` de R-13), `app/api/budget/planning.py` (hook),
`app/api/budget/collaborator.py` (+status route + `MaterializationStatusOut` en
`schemas/budget/collaborator.py`, exportado en ambos `__init__`). Contratos FE:
`frontend.03_15` §12. AC nuevos: AC-MAT-1 (importar nómina sin escenario activo →
crear/activar meta después → líneas materializadas ese mismo request, `payroll_lines_created>0`);
AC-MAT-2 (activación con vigencia sin parámetros → 200, activación persiste,
`payroll_warnings` con el texto R-05, cero líneas); AC-MAT-3 (set-target de una meta ya
proyectada → reemplazo idempotente, conteo de líneas idéntico); AC-MAT-4 (status:
with_plan>0 y lines==0 → `needs_materialization=true`; tras recalcular → false).
