"""
Budget Planning LINE Manager Smoke Tests (BE-S4D-BUDGET-LINES)

Spec: crm_backend/spec/backend.02_13_Spec_Backend_budgets_planning_lines.md §7.

Cubre contra el backend corriendo (dev) los 3 endpoints nuevos del
sub-router /budget/planning:

    POST   /budget/planning/{id_budget}/line       (201 BudgetLine)
    PUT    /budget/planning/line/{id_budget_line}  (200 BudgetLine)
    DELETE /budget/planning/line/{id_budget_line}  (200 {deleted_id})

    AC-LINE-1   creacion fixed-income: 201, detalle la incluye, Σ listing
    AC-LINE-2   variable fuerza monto 0 (BR-LINE-03); sin tasa -> 422
    AC-LINE-3   anio budget_date != anio escenario -> 400 exacto;
                payment_date anio+1 LICITO -> 201 (sin check de anio)
    AC-LINE-4   FKs inexistentes -> 404 (CECO / coleccion / presupuesto)
    AC-LINE-5   PUT estructural (CECO+fechas+coleccion+monto+descrip) con
                lectura FRESH del detail (no de la respuesta)
    AC-LINE-6   PUT monto en variable -> 400; PUT tasa 0.05->0.08 -> 200 y
                la analitica que CONSUME la tasa (cash-flow-projection,
                BR-16: get_pnl solo suma projected_amount) refleja +delta
                exacto; pnl del periodo responde 200 (contrato intacto)
    AC-LINE-7   PUT con line_type/behavior_type -> 200 e INVARIANTES
    AC-LINE-8   PUT/DELETE id fantasma -> 404; DELETE fisico: desaparece
                de detail y Σ del listado baja exacto; sobre cerrado -> 200
    AC-LINE-9   -1 -> 422; tasa 19 -> 422; tasa en fixed -> 400 (BR-LINE-07)
    AC-LINE-10  sin JWT -> 401 en los 3; openapi.json (sin auth) muestra
                los 3 paths + PlanningLineCreate/Update en components
    AC-LINE-11  (externo) python test/test_budget_planning_smoke.py verde
    AC-LINE-12  cero DDL: columnas de budgets/budget_lines identicas
                antes/despues

Aislamiento: fixture creado por SQL directo con el anio centinela 2099 y
prefijo "PLNL " (no colisiona con el smoke 02_12 que usa 2027/'PLN ').
Pre-clean y post-clean GARANTIZADOS (try/finally): "borrar el clon YA" --
se eliminan via SQL todas las lineas y presupuestos 2099 creados por el
test, y se verifica 0 restos al final.

Uso:
    1. docker compose -f docker-compose-dev.yaml up   (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD
    3. python test/test_budget_planning_lines_smoke.py   (desde crm_backend/)

Notas de entorno: psycopg2 si esta disponible (venv_backend); si no,
fallback a `docker exec db_crm_dev psql` (igual que el smoke 02_12).
"""

import sys
import time
import traceback
from pathlib import Path

import requests
from dotenv import dotenv_values

try:
    import psycopg2  # opcional: se prefiere sobre docker exec
except Exception:  # pragma: no cover
    psycopg2 = None

# Consolas de Windows (cp1252) no codifican los caracteres del reporte
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ══════════════════════════════════════════════════════════════
# CONFIGURACION
# ══════════════════════════════════════════════════════════════

TEST_DIR = Path(__file__).parent
ENV_FILE = TEST_DIR / ".env_test"
DEV_ENV_FILE = TEST_DIR.parent / ".env.development"

if not ENV_FILE.exists():
    print(f"ERROR: No se encontro {ENV_FILE}")
    print("Copia .env_test.example a .env_test y configura tus credenciales")
    sys.exit(1)

config = dotenv_values(ENV_FILE)
dev_config = dotenv_values(DEV_ENV_FILE) if DEV_ENV_FILE.exists() else {}


def _cfg(key, default=""):
    return (config.get(key) or default).strip('"\'')


BASE_URL = _cfg("BASE_URL", "http://127.0.0.1:8003")
USERNAME = _cfg("USERNAME")
PASSWORD = _cfg("PASSWORD")

PG_HOST = _cfg("PG_HOST", "127.0.0.1")
PG_PORT = int(_cfg("PG_PORT", "5433"))
PG_USER = _cfg("PG_USER") or dev_config.get("POSTGRES_USER", "postgres")
PG_PASSWORD = _cfg("PG_PASSWORD") or dev_config.get("POSTGRES_PASSWORD", "")
PG_DB = _cfg("PG_DB") or dev_config.get("POSTGRES_DB", "crm")
PG_DOCKER = _cfg("PG_DOCKER_CONTAINER", "db_crm_dev")

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# CONSTANTES DEL TEST
# ══════════════════════════════════════════════════════════════

MARK = "PLNL "     # prefijo de aislamiento de nombres (!= 'PLN ' del 02_12)
YEAR = 2099        # anio centinela (limpio: 0 presupuestos historicos)
TOL = 1e-6

YEAR_400 = "budget_date year 2098 does not match scenario year 2099"
VAR_400 = ("variable lines derive their amount from the rate; "
           "edit variable_rate instead")

# Montos del fixture (base de junio para la proyeccion de caja variable)
INC_JUN = 10_000_000.0    # fixed income junio (seed SQL)
EXP_MAR = 500_000.0       # fixed expense marzo (target AC-LINE-5/7/8)
RATE0 = 0.05              # tasa inicial de la variable junio (seed)
RATE1 = 0.08              # nueva tasa (AC-LINE-6)
VAR2_RATE = 0.07          # segunda variable junio creada en AC-LINE-2

state = type("S", (), {})()
state.headers = {}
state.token = None
state.created_budgets = []
state.fix_id = None       # escenario draft para las mutaciones
state.closed_id = None    # escenario closed (BR-LINE-05)
state.inc1 = None         # id linea income junio seed
state.var1 = None         # id linea variable_sales junio seed (rate .05)
state.fix1 = None         # id linea fixed expense marzo seed
state.inc_closed = None   # id linea income del escenario closed
state.cc1 = None
state.cc2 = None
state.coll1 = None
state.ddl_start = None
state.total = 0
state.passed = 0
state.failed = 0
state.results = []


# ══════════════════════════════════════════════════════════════
# UTILIDADES (mismos patrones del smoke 02_12)
# ══════════════════════════════════════════════════════════════

def api(method, endpoint, auth=True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = dict(state.headers) if auth else {}
    headers.update(kwargs.pop("headers", {}))
    try:
        return requests.request(method, url, headers=headers, timeout=60, **kwargs)
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Request exception: {type(e).__name__}: {str(e)[:100]}")
        return None


def ck(name, ok, detail=""):
    """Registra un check booleano (estilo test_*_smoke.py)."""
    status = "[PASS]" if ok else "[FAIL]"
    state.total += 1
    msg = f"[{state.total}] {name}... {status}"
    if detail:
        msg += f" ({detail})"
    print(msg)
    if ok:
        state.passed += 1
    else:
        state.failed += 1
    state.results.append((name, ok, detail))
    return ok


def run_sql(sql, fetch=False):
    """Ejecuta SQL de apoyo: psycopg2 si existe, si no docker exec psql."""
    if psycopg2 is not None:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                                password=PG_PASSWORD, dbname=PG_DB)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall() if fetch else None
            conn.commit()
            return rows
        finally:
            conn.close()
    import subprocess
    cmd = ["docker", "exec", PG_DOCKER, "psql", "-U", PG_USER, "-d", PG_DB,
           "-tAc", sql]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"psql fallo: {out.stderr.strip()[:200]}")
    if not fetch:
        return None
    lines = [l for l in out.stdout.splitlines() if l.strip() != ""]
    return [tuple(l.split("|")) for l in lines]


def sql_scalar(sql):
    rows = run_sql(sql, fetch=True)
    return rows[0][0] if rows else None


def insert_budget(name, status_kind):
    return int(sql_scalar(
        f"INSERT INTO budgets (budget_name, budget_year, budget_period, status)"
        f" VALUES ('{name}', {YEAR}, 'ANUAL', '{status_kind}') "
        f"RETURNING id_budget"))


def insert_line(budget_id, cc, ltype, bdate, pdate, coll, amount, desc,
                behavior, rate):
    p = f"'{pdate}'" if pdate else "NULL"
    c = str(coll) if coll else "NULL"
    r = str(rate) if rate is not None else "NULL"
    d = f"'{desc}'" if desc else "NULL"
    return int(sql_scalar(
        "INSERT INTO budget_lines (id_budget, id_cost_center, line_type, "
        "budget_date, payment_date, id_collection, projected_amount, "
        "description, behavior_type, variable_rate) VALUES "
        f"({budget_id}, {cc}, '{ltype}', '{bdate}', {p}, {c}, {amount}, "
        f"{d}, '{behavior}', {r}) RETURNING id_budget_line"))


def line_in_detail(budget_id, line_id):
    r = api("GET", f"/budget/planning/{budget_id}/detail")
    if r is None or r.status_code != 200:
        return None
    return next((l for l in r.json()["budget_lines"]
                 if l["id_budget_line"] == line_id), None)


def db_line(line_id):
    """Lectura cruda (psycopg2/psql) para verificar persistencia real."""
    rows = run_sql(
        "SELECT id_cost_center, line_type, budget_date, payment_date, "
        "id_collection, projected_amount, description, behavior_type, "
        f"variable_rate FROM budget_lines WHERE id_budget_line={line_id}",
        fetch=True)
    return rows[0] if rows else None


def planning_row(budget_id):
    r = api("GET", f"/budget/planning/?budget_year={YEAR}")
    if r is None or r.status_code != 200:
        return None
    return next((row for row in r.json() if row["id_budget"] == budget_id), None)


def june_outflows(budget_id):
    """expected_outflows del mes 6 en la proyeccion de caja del motor
    (unica vista analitica que CONSUME variable_rate; BR-16 en get_pnl)."""
    r = api("GET", f"/budget/analytics/cash-flow-projection"
                   f"?budget_year={YEAR}&id_budget={budget_id}")
    if r is None or r.status_code != 200:
        return None
    return next((p["expected_outflows"] for p in r.json()
                 if p["payment_month"] == 6), None)


def ddl_snapshot():
    cols = run_sql(
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_name IN ('budgets','budget_lines') ORDER BY 1,2",
        fetch=True) or []
    regs = run_sql(
        "SELECT to_regclass('public.budgets'), to_regclass('public.budget_lines')",
        fetch=True) or []
    return (tuple(map(tuple, cols)), tuple(map(str, regs[0])) if regs else ())


# ══════════════════════════════════════════════════════════════
# LIMPIEZA (pre/post garantizados)
# ══════════════════════════════════════════════════════════════

def sweep_2099():
    """Borra lineas y presupuestos del anio centinela (orden FK-safe)."""
    run_sql("DELETE FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_year={YEAR})")
    run_sql("DELETE FROM budgets WHERE budget_year="
            f"{YEAR} AND budget_name LIKE '{MARK.strip()}%'")
    run_sql(f"DELETE FROM budgets WHERE budget_year={YEAR}")


def preclean():
    try:
        sweep_2099()
    except Exception:
        traceback.print_exc()


def postclean():
    try:
        sweep_2099()
        rest_l = int(sql_scalar(
            "SELECT count(*) FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_year={YEAR})"))
        rest_b = int(sql_scalar(
            f"SELECT count(*) FROM budgets WHERE budget_year={YEAR}"))
        ck("Limpieza garantizada: 0 lineas + 0 presupuestos 2099 restantes",
           rest_l == 0 and rest_b == 0, f"lineas={rest_l} budgets={rest_b}")
    except Exception:
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════
# PRUEBAS
# ══════════════════════════════════════════════════════════════

def t01_login():
    r = api("POST", "/login/", auth=False,
            json={"username": USERNAME, "password": PASSWORD})
    if r is not None and r.status_code == 200:
        state.token = r.json().get("access_token")
        state.headers = {"Authorization": f"Bearer {state.token}"}
        return ck("00. Login admin (JWT)", bool(state.token))
    return ck("00. Login admin (JWT)", False,
              (r.text[:80] if r is not None else "error"))


def t02_seed_fixture():
    """Fixture aislado 2099 via SQL directo: 1 draft + 1 closed con lineas
    conocidas (base junio = INC_JUN para la prueba de tasa diferencial)."""
    state.cc1 = int(sql_scalar("SELECT min(id_cost_center) FROM cost_centers"))
    state.cc2 = int(sql_scalar(
        "SELECT id_cost_center FROM cost_centers "
        "WHERE id_cost_center <> "
        f"{state.cc1} ORDER BY id_cost_center LIMIT 1"))
    state.coll1 = sql_scalar("SELECT min(id_collection) FROM collections")

    # precondiciones: anio centinela sin datos que contaminen la proyeccion
    ar = int(sql_scalar(
        f"SELECT count(*) FROM accounts_receivable "
        f"WHERE extract(year FROM due_date)={YEAR}"))
    ap = int(sql_scalar(
        f"SELECT count(*) FROM accounts_payable "
        f"WHERE extract(year FROM due_date)={YEAR}"))
    ck("Precondicion: 0 cuentas por cobrar/pagar en 2099 "
       "(proyeccion de caja = solo lineas del fixture)", ar == 0 and ap == 0,
       f"ar={ar} ap={ap}")
    if not state.cc2:
        return ck("Fixture: >= 2 centros de costo disponibles", False)

    state.fix_id = insert_budget(MARK + "base 2099", "draft")
    state.closed_id = insert_budget(MARK + "cerrado 2099", "closed")
    state.created_budgets = [state.fix_id, state.closed_id]
    state.inc1 = insert_line(state.fix_id, state.cc1, "INCOME",
                             "2099-06-30", "2099-06-30", None, INC_JUN,
                             "seed income junio", "FIXED", None)
    state.var1 = insert_line(state.fix_id, state.cc1, "EXPENSE",
                             "2099-06-30", None, None, 0,
                             "seed variable junio", "VARIABLE_SALES", RATE0)
    state.fix1 = insert_line(state.fix_id, state.cc2, "EXPENSE",
                             "2099-03-31", "2099-03-31", None, EXP_MAR,
                             "seed fixed marzo", "FIXED", None)
    state.inc_closed = insert_line(state.closed_id, state.cc1, "INCOME",
                                   "2099-06-30", None, None, 1_000_000.0,
                                   "seed income cerrado", "FIXED", None)

    row = planning_row(state.fix_id)
    ok = (row is not None and row["status"] == "draft"
          and row["lines_count"] == 3
          and abs(row["total_income"] - INC_JUN) < TOL
          and abs(row["total_expense"] - EXP_MAR) < TOL)
    ck("Fixture 2099 sembrado via SQL (3 lineas; Σ listing correctos)", ok,
       (f"{row and {k: row[k] for k in ('lines_count', 'total_income', 'total_expense')}}"))
    state.ddl_start = ddl_snapshot()
    return row is not None


def t03_jwt_guard():
    """AC-LINE-10 (1a parte): sin JWT -> 401 en los 3 endpoints."""
    r1 = api("POST", f"/budget/planning/{state.fix_id}/line", auth=False,
             json={"id_cost_center": state.cc1, "line_type": "income",
                   "budget_date": "2099-01-01"})
    r2 = api("PUT", "/budget/planning/line/1", auth=False,
             json={"description": "x"})
    r3 = api("DELETE", "/budget/planning/line/1", auth=False)
    # OJO: Response.__bool__ es False para 4xx/5xx -> usar "is not None"
    codes = [r.status_code if r is not None else 0 for r in (r1, r2, r3)]
    return ck("AC-LINE-10 POST/PUT/DELETE sin JWT -> 401/401/401",
              all(c in (401, 403) for c in codes), f"codes={codes}")


def t04_ac_line_1():
    """AC-LINE-1: POST fixed-income -> 201, aparece en detail, Σ sube exacto."""
    before = planning_row(state.fix_id)
    amount = 2_500_000.25
    r = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "income",
        "budget_date": "2099-05-15", "payment_date": "2099-05-28",
        "projected_amount": amount, "description": "AC-LINE-1",
    })
    if r is None or r.status_code != 201:
        return ck("AC-LINE-1 POST fixed-income -> 201", False,
                  (r.text[:150] if r is not None else "error"))
    body = r.json()
    state.line_ac1 = body["id_budget_line"]
    ck("AC-LINE-1 201 con id_budget_line > 0 e id_budget del path",
       isinstance(body["id_budget_line"], int) and body["id_budget_line"] > 0
       and body["id_budget"] == state.fix_id, f"id={body['id_budget_line']}")
    ck("AC-LINE-1 respuesta BudgetLine completa con los campos del body "
       "(NFR-L-2, fechas ISO)",
       body["line_type"] == "income" and body["behavior_type"] == "fixed"
       and abs(body["projected_amount"] - amount) < TOL
       and body["budget_date"] == "2099-05-15"
       and body["payment_date"] == "2099-05-28"
       and body["description"] == "AC-LINE-1")
    fresh = line_in_detail(state.fix_id, state.line_ac1)
    ck("AC-LINE-1 GET .../detail incluye la linea nueva", fresh is not None)
    after = planning_row(state.fix_id)
    ck("AC-LINE-1 Σ total_income del listado sube EXACTAMENTE el monto",
       abs(after["total_income"] - (before["total_income"] + amount)) < 0.01,
       f"{before['total_income']} -> {after['total_income']} (+{amount})")
    raw = db_line(state.line_ac1)
    ck("AC-LINE-1 verificacion SQL directa (psycopg2): fila persistida",
       raw is not None and float(raw[5]) == amount and raw[6] == "AC-LINE-1")
    return True


def t05_ac_line_2():
    """AC-LINE-2: variable fuerza monto 0 (BR-LINE-03); sin tasa 422."""
    r = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "expense",
        "budget_date": "2099-06-20", "projected_amount": 500000,
        "behavior_type": "variable_sales", "variable_rate": VAR2_RATE,
        "description": "AC-LINE-2",
    })
    if r is None or r.status_code != 201:
        return ck("AC-LINE-2 POST variable_sales -> 201", False,
                  (r.text[:150] if r is not None else "error"))
    body = r.json()
    state.var2 = body["id_budget_line"]
    ck("AC-LINE-2/BR-LINE-03 projected_amount FORZADO a 0 (body pidio 500000)",
       body["projected_amount"] == 0
       and body["behavior_type"] == "variable_sales"
       and abs(body["variable_rate"] - VAR2_RATE) < TOL)
    raw = db_line(state.var2)
    ck("AC-LINE-2 persistencia SQL: monto 0 con tasa 0.07 intacta",
       raw is not None and float(raw[5]) == 0 and abs(float(raw[8]) - VAR2_RATE) < TOL)
    r2 = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "expense",
        "budget_date": "2099-07-01", "behavior_type": "variable_sales",
    })
    ck("AC-LINE-2 variable sin variable_rate -> 422 (validador)",
       r2 is not None and r2.status_code == 422,
       f"status={r2 and r2.status_code}")
    return True


def t06_ac_line_3():
    """AC-LINE-3: anio budget_date 400 exacto; payment_date anio+1 -> 201."""
    r = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "income",
        "budget_date": "2098-06-15", "projected_amount": 100,
    })
    ok400 = (r is not None and r.status_code == 400
             and r.json().get("detail") == YEAR_400)
    ck("AC-LINE-3/BR-LINE-04 budget_date 2098 en escenario 2099 -> 400 "
       "con detalle exacto", ok400, (r.text[:120] if r is not None else "error"))

    r2 = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "income",
        "budget_date": "2099-09-01", "payment_date": "2100-01-31",
        "projected_amount": 300_000.0, "description": "pago enero+1 licito",
    })
    ok201 = (r2 is not None and r2.status_code == 201
             and r2.json()["payment_date"] == "2100-01-31")
    if ok201:
        state.pago2100 = r2.json()["id_budget_line"]
    return ck("AC-LINE-3 payment_date 2100-01-31 (anio+1) sin check de anio "
              "-> 201", ok201, (r2.text[:120] if r2 is not None else "error"))


def t07_ac_line_4():
    """AC-LINE-4: FKs/padre inexistentes -> 404 con detalles §3.4."""
    base_body = {"line_type": "income", "budget_date": "2099-08-01",
                 "projected_amount": 10}
    r1 = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        **base_body, "id_cost_center": 999999})
    ok1 = (r1 is not None and r1.status_code == 404
           and r1.json().get("detail") == "Cost center 999999 not found")
    r2 = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        **base_body, "id_cost_center": state.cc1, "id_collection": 999999})
    ok2 = (r2 is not None and r2.status_code == 404
           and r2.json().get("detail") == "Collection 999999 not found")
    r3 = api("POST", "/budget/planning/999999999/line", json={
        **base_body, "id_cost_center": state.cc1})
    ok3 = (r3 is not None and r3.status_code == 404
           and r3.json().get("detail") == "Budget 999999999 not found")
    ck("AC-LINE-4/BR-LINE-02 CECO inexistente -> 404 'Cost center 999999 not found'",
       ok1, (r1.text[:100] if r1 is not None else "error"))
    ck("AC-LINE-4/BR-LINE-02 coleccion inexistente -> 404 'Collection 999999 not found'",
       ok2, (r2.text[:100] if r2 is not None else "error"))
    return ck("AC-LINE-4/BR-LINE-01 presupuesto inexistente -> 404 'Budget 999999999 not found'",
              ok3, (r3.text[:100] if r3 is not None else "error"))


def t08_nfr_l1_latency():
    """NFR-L-1: 5 POST de mutacion unitaria -> mediana < 150 ms (dev)."""
    warm = api("POST", f"/budget/planning/{state.fix_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "income",
        "budget_date": "2099-12-01", "projected_amount": 1,
    })  # warmup (post-reload); se borra inmediatamente
    if warm is not None and warm.status_code == 201:
        api("DELETE", f"/budget/planning/line/{warm.json()['id_budget_line']}")
    times, ids = [], []
    for i in range(5):
        t0 = time.perf_counter()
        r = api("POST", f"/budget/planning/{state.fix_id}/line", json={
            "id_cost_center": state.cc1, "line_type": "income",
            "budget_date": "2099-12-01", "projected_amount": 1000 + i,
            "description": f"latency {i}",
        })
        times.append((time.perf_counter() - t0) * 1000)
        if r is not None and r.status_code == 201:
            ids.append(r.json()["id_budget_line"])
            api("DELETE", f"/budget/planning/line/{ids[-1]}")
    median = sorted(times)[len(times) // 2]
    return ck("NFR-L-1 mediana 5 POST /line < 150 ms (dev local)",
              median < 150, f"mediana={median:.0f} ms, muestras={[f'{t:.0f}' for t in times]}")


def t09_ac_line_5():
    """AC-LINE-5: PUT estructural sobre fixed -> 200 + persistencia leida
    por detail FRESH (no de la respuesta)."""
    body = {"id_cost_center": state.cc1, "budget_date": "2099-04-10",
            "payment_date": "2099-04-18", "projected_amount": 750_000.5,
            "description": "AC-LINE-5 editada"}
    if state.coll1:
        body["id_collection"] = int(state.coll1)
    r = api("PUT", f"/budget/planning/line/{state.fix1}", json=body)
    if r is None or r.status_code != 200:
        return ck("AC-LINE-5 PUT estructural fixed -> 200", False,
                  (r.text[:150] if r is not None else "error"))
    resp = r.json()
    fresh = line_in_detail(state.fix_id, state.fix1)
    want = {"id_cost_center": state.cc1, "budget_date": "2099-04-10",
            "payment_date": "2099-04-18", "projected_amount": 750_000.5,
            "description": "AC-LINE-5 editada"}
    if state.coll1:
        want["id_collection"] = int(state.coll1)
    ok_fresh = fresh is not None and all(
        fresh[k] == v for k, v in want.items())
    ck("AC-LINE-5 detail FRESH muestra CECO+fechas+coleccion+monto+descrip "
       "nuevos", ok_fresh, f"fresh={fresh and {k: fresh.get(k) for k in want}}")
    ok_resp = all(resp.get(k) == v for k, v in want.items())
    ck("AC-LINE-5/NFR-L-2 la respuesta 200 trae el objeto completo == DB",
       ok_resp, f"resp={resp and {k: resp.get(k) for k in want}}")
    raw = db_line(state.fix1)
    ck("AC-LINE-5 verificacion SQL directa de la edicion",
       raw is not None and int(raw[0]) == state.cc1 and str(raw[2]) == "2099-04-10"
       and abs(float(raw[5]) - 750_000.5) < TOL)
    return True


def t10_ac_line_6():
    """AC-LINE-6: monto en variable -> 400; tasa .05->.08 -> 200 y la
    analitica que consume la tasa (cash-flow-projection, BR-16) refleja el
    delta exacto; get_pnl del periodo responde 200 con contrato intacto."""
    r400 = api("PUT", f"/budget/planning/line/{state.var1}",
               json={"projected_amount": 123})
    ok400 = (r400 is not None and r400.status_code == 400
             and r400.json().get("detail") == VAR_400)
    ck("AC-LINE-6/BR-LINE-07 PUT projected_amount en variable -> 400 "
       "con detalle exacto", ok400,
       (r400.text[:130] if r400 is not None else "error"))

    june0 = june_outflows(state.fix_id)
    exp0 = INC_JUN * (RATE0 + VAR2_RATE)
    ck("AC-LINE-6 junio antes de la edicion: outflows == Σ tasa x base "
       f"(10M x ({RATE0}+{VAR2_RATE}))",
       june0 is not None and abs(june0 - exp0) < 0.01, f"june={june0} exp={exp0}")

    r = api("PUT", f"/budget/planning/line/{state.var1}",
            json={"variable_rate": RATE1})
    ok200 = (r is not None and r.status_code == 200
             and abs(r.json()["variable_rate"] - RATE1) < TOL
             and r.json()["behavior_type"] == "variable_sales")
    ck("AC-LINE-6 PUT variable_rate=0.08 en variable -> 200 con tasa "
       "persistida", ok200, (r.text[:130] if r is not None else "error"))

    june1 = june_outflows(state.fix_id)
    exp1 = INC_JUN * (RATE1 + VAR2_RATE)
    ck("AC-LINE-6 analitica refleja la nueva tasa: junio == 10M x "
       f"(0.08+0.07) == {exp1:,.2f}",
       june1 is not None and abs(june1 - exp1) < 0.01,
       f"june={june1} exp={exp1}")

    pnl = api("GET", f"/budget/analytics/pnl?date_from={YEAR}-06-01"
                     f"&date_to={YEAR}-06-30&id_budget={state.fix_id}")
    pnl_ok = (pnl is not None and pnl.status_code == 200
              and (pnl.json()["meta"].get("budget_source") or {}).get(
                  "id_budget") == state.fix_id)
    return ck("AC-LINE-6 get_pnl del periodo cubierto responde 200 con el "
              "escenario resuelto (contrato NFR-L-4 intacto)", pnl_ok,
              (f"status={pnl and pnl.status_code}"))


def t11_ac_line_9():
    """AC-LINE-9: -1 -> 422; tasa 19 -> 422; tasa en fixed -> 400 analogo."""
    r1 = api("PUT", f"/budget/planning/line/{state.var1}",
             json={"projected_amount": -1})
    r2 = api("PUT", f"/budget/planning/line/{state.fix1}",
             json={"variable_rate": 19})
    r3 = api("PUT", f"/budget/planning/line/{state.fix1}",
             json={"variable_rate": 0.08})
    ok1 = r1 is not None and r1.status_code == 422   # ge=0 pydantic
    ok2 = r2 is not None and r2.status_code == 422   # le=1 pydantic (0-1)
    ok3 = r3 is not None and r3.status_code == 400   # BR-LINE-07 fixed+tasa
    ck("AC-LINE-9 PUT projected_amount=-1 -> 422 (ge=0)", ok1,
       f"status={r1 and r1.status_code}")
    ck("AC-LINE-9 PUT variable_rate=19 -> 422 (le=1; el FE convierte %)", ok2,
       f"status={r2 and r2.status_code}")
    return ck("AC-LINE-6/BR-LINE-07 PUT variable_rate en fixed -> 400 analogo",
              ok3, (r3.text[:130] if r3 is not None else "error"))


def t12_ac_line_7():
    """AC-LINE-7: PUT con line_type/behavior_type -> 200 e invariantes."""
    before = line_in_detail(state.fix_id, state.fix1)
    r = api("PUT", f"/budget/planning/line/{state.fix1}", json={
        "line_type": "income", "behavior_type": "variable_sales",
        "description": "AC-LINE-7",
    })
    if r is None or r.status_code != 200:
        return ck("AC-LINE-7/BR-LINE-06 PUT con type/behavior -> 200 "
                  "(ignorados, extra=ignore)", False,
                  (r.text[:130] if r is not None else "error"))
    fresh = line_in_detail(state.fix_id, state.fix1)
    ck("AC-LINE-7/BR-LINE-06 line_type y behavior_type INVARIANTES tras el PUT",
       fresh["line_type"] == before["line_type"] == "expense"
       and fresh["behavior_type"] == before["behavior_type"] == "fixed")
    return ck("AC-LINE-7 el PUT con extra-campos aun aplica los validos "
              "(description)", fresh["description"] == "AC-LINE-7")


def t13_ac_line_8():
    """AC-LINE-8: 404 en id fantasma; DELETE fisico baja Σ exacto; cerrado OK."""
    ghost = 999999999
    r1 = api("PUT", f"/budget/planning/line/{ghost}", json={"description": "x"})
    r2 = api("DELETE", f"/budget/planning/line/{ghost}")
    ok1 = (r1 is not None and r1.status_code == 404
           and r1.json().get("detail") == f"BudgetLine {ghost} not found")
    ok2 = (r2 is not None and r2.status_code == 404
           and r2.json().get("detail") == f"BudgetLine {ghost} not found")
    ck("AC-LINE-8 PUT id_budget_line inexistente -> 404 'BudgetLine 999999999 not found'",
       ok1, (r1.text[:100] if r1 is not None else "error"))
    ck("AC-LINE-8 DELETE id_budget_line inexistente -> 404 mismo detalle",
       ok2, (r2.text[:100] if r2 is not None else "error"))

    before = planning_row(state.fix_id)
    amount = 750_000.5  # fix1 tras AC-LINE-5
    r3 = api("DELETE", f"/budget/planning/line/{state.fix1}")
    ok3 = (r3 is not None and r3.status_code == 200
           and r3.json() == {"deleted_id": state.fix1})
    ck("AC-LINE-8 DELETE exitoso -> 200 {deleted_id}", ok3,
       (r3.text[:100] if r3 is not None else "error"))
    ck("AC-LINE-8 la linea desaparece de .../detail (borrado fisico)",
       line_in_detail(state.fix_id, state.fix1) is None)
    after = planning_row(state.fix_id)
    ck("AC-LINE-8 Σ total_expense del listado baja EXACTAMENTE el monto",
       abs(after["total_expense"] - (before["total_expense"] - amount)) < 0.01,
       f"{before['total_expense']} -> {after['total_expense']}")
    ck("AC-LINE-8 verificacion SQL: fila realmente eliminada",
       db_line(state.fix1) is None)

    r4 = api("POST", f"/budget/planning/{state.closed_id}/line", json={
        "id_cost_center": state.cc1, "line_type": "expense",
        "budget_date": "2099-10-10", "projected_amount": 42_000.0,
        "description": "BR-LINE-05 closed",
    })
    ok5 = r4 is not None and r4.status_code == 201
    ck("AC-LINE-8/BR-LINE-05 POST sobre escenario closed -> 201 (sin lock)",
       ok5, (r4.text[:100] if r4 is not None else "error"))
    r5 = api("DELETE", f"/budget/planning/line/{state.inc_closed}")
    return ck("AC-LINE-8/BR-LINE-05 DELETE sobre linea de escenario closed -> 200",
              r5 is not None and r5.status_code == 200
              and r5.json() == {"deleted_id": state.inc_closed},
              (r5.text[:100] if r5 is not None else "error"))


def t14_cell_regression():
    """NFR-L-5 (micro-regresion local): PUT /cell sigue vivo e inmutable."""
    r = api("PUT", f"/budget/planning/cell/{state.inc1}",
            json={"projected_amount": INC_JUN})
    ok = (r is not None and r.status_code == 200
          and r.json()["id_budget_line"] == state.inc1
          and abs(r.json()["projected_amount"] - INC_JUN) < TOL)
    return ck("NFR-L-5 PUT /cell/{id} sigue respondiendo 200 (D-8)", ok,
              (r.text[:100] if r is not None else "error"))


def t15_openapi():
    """AC-LINE-10 (2a parte): /openapi.json sin auth: 3 paths + schemas."""
    r = requests.get(f"{BASE_URL}/openapi.json", timeout=30)
    if r is None or r.status_code != 200:
        return ck("AC-LINE-10/NFR-L-3 GET /openapi.json sin auth -> 200", False)
    spec = r.json()
    paths = spec.get("paths", {})
    p_create = paths.get("/budget/planning/{id_budget}/line", {})
    p_line = paths.get("/budget/planning/line/{id_budget_line}", {})
    ck("AC-LINE-10 los 3 paths nuevos aparecen en openapi",
       "post" in p_create and "put" in p_line and "delete" in p_line)
    schemas = spec.get("components", {}).get("schemas", {})
    ck("AC-LINE-10 PlanningLineCreate y PlanningLineUpdate registrados en components",
       "PlanningLineCreate" in schemas and "PlanningLineUpdate" in schemas,
       f"keys={[k for k in schemas if k.startswith('PlanningLine')]}")

    def ref_of(node, key):
        return (node.get("requestBody", {}).get("content", {})
                .get("application/json", {}).get("schema", {}).get("$ref", key))

    post_ok = ("post" in p_create
               and str(p_create["post"]["responses"].get("201", {})) != "{}"
               and ref_of(p_create["post"], "\x00")
               == "#/components/schemas/PlanningLineCreate"
               and "application/json" in p_create["post"]["responses"]["201"]
                   .get("content", {})
               and p_create["post"]["responses"]["201"]["content"]
                   ["application/json"]["schema"].get("$ref")
               == "#/components/schemas/BudgetLine")
    put_ok = ("put" in p_line
              and ref_of(p_line["put"], "\x00")
              == "#/components/schemas/PlanningLineUpdate"
              and p_line["put"]["responses"].get("200", {}).get("content", {})
              .get("application/json", {}).get("schema", {}).get("$ref")
              == "#/components/schemas/BudgetLine")
    del_ok = "delete" in p_line and "200" in p_line["delete"]["responses"]
    return ck("NFR-L-3 response/request models correctos en los 3 endpoints "
              "(POST 201 BudgetLine+Create; PUT 200 BudgetLine+Update; DELETE 200)",
              post_ok and put_ok and del_ok,
              f"post={post_ok} put={put_ok} delete={del_ok}")


def t16_ac_line_12():
    """AC-LINE-12: cero DDL (columnas/tablas fuente identicas)."""
    end = ddl_snapshot()
    return ck("AC-LINE-12 cero DDL: information_schema + to_regclass sin "
              "cambios", end == state.ddl_start,
              f"cols_inicio={len(state.ddl_start[0])} cols_fin={len(end[0])}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Budget Planning Line Manager Smoke (BE-S4D-BUDGET-LINES)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Anio centinela: {YEAR} | prefijo aislado: '{MARK}*'")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    if not t02_seed_fixture():
        print("ABORT: fixture de prueba no pudo crearse")
        postclean()
        return 1
    print()

    tests = [
        t03_jwt_guard,
        t04_ac_line_1,
        t05_ac_line_2,
        t06_ac_line_3,
        t07_ac_line_4,
        t08_nfr_l1_latency,
        t09_ac_line_5,
        t10_ac_line_6,
        t11_ac_line_9,
        t12_ac_line_7,
        t13_ac_line_8,
        t14_cell_regression,
        t15_openapi,
        t16_ac_line_12,
    ]
    try:
        for t in tests:
            try:
                t()
            except Exception as e:
                ck(f"{t.__name__} (excepcion)", False,
                   f"{type(e).__name__}: {str(e)[:140]}")
                traceback.print_exc()
    finally:
        print()
        print("-- post-clean --")
        postclean()

    print()
    print("=" * 64)
    print(f"Resultados: {state.passed}/{state.total} checks pasaron")
    if state.failed:
        print("FALLOS:")
        for name, ok, detail in state.results:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 64)
    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
