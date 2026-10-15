"""
Budget IVA Settlement Smoke Tests (BE-S10-IVA)

Spec: crm_backend/spec/backend.02_20_Spec_Backend_budgets_iva_settlement.md
§9. Patron de test_budget_internment_smoke.py: corre contra el backend dev
real (:8003), JWT de .env_test, SQL de apoyo por psycopg2 (fallback docker
exec psql, con NULL-SENTINEL -P) y una seccion UNIT in-process (importa
app.services.budgetIvaEngine y el ETL app.utils.templates contra la misma
BD dev) para los edges de derivacion §4, la tabla de valores §5.6, la
paridad HTTP-vs-unit del contrato §4.6 y la economia/pureza medidas
(NFR-BE10-1/2).

Cubre (numerales EXACTOS de spec §9):
     AC-BE10-1 (ETL/flag): legacy upload con columna Con IVA: No =>
               has_iva False; Si/si/X => True; celda vacia => None.
               Archivo SIN la columna (planning upload 3 archivos) =>
               todas None (income/purchase/builders intactos) y subida
               identica a hoy (AC-REG-01: mismas claves de respuesta,
               mismas filas). El flag persiste en budget_lines y sale en
               GET /{id}/detail. Tabla §5.6 completa chequeada in-
               process (si/si/yes/y/x/1/true/verdadero; no/not/n/false/
               0/falso; NaN/vacio/otro => None; numericos 1.0/0.0).
     AC-BE10-2 (line manager): POST /line sin campo => True; PUT
               {has_iva:false} => reflejado y persistente; PUT omitido
               => keep. El flag de una INCOME se acepta y persiste pero
               NO altera su evento E1 (siempre gravada); el de una
               PURCHASE NO altera E5 (§3.1, siempre gravada).
     AC-BE10-3 (eventos de compra): fixture 10.000.000 fecha 2027-01-10
               %int .10, terminos int +15@.6/+45@.4 => E5 = 1.727.272,73
               en 2027-01-10; E6 = 103.636,36 (2027-01-25) + 69.090,91
               (2027-02-24); SIGMA = 1.900.000,00 = T x Total exacto.
               Sin %int (Linea B): E5 = 1.900.000 en la ancla 2027-01-20
               y CERO E6. HTTP: P1 import_vat 3.627.272,73 +
               nationalization_vat 172.727,27, events_count 4, y el
               escenario (puro descontable) cierra con arrastre
               ilimitado 3.800.000 en todos los periodos (D-S10-11).
     AC-BE10-4 (recurrencia con arrastre): bimestral 2027 (P1 ene-feb
               vence 2027-05-21); P1 1.900.000/0 => pago 1.900.000; P2
               0/2.500.000 => pago 0 arrastre 2.500.000; P3
               3.000.000/1.000.000 => base -500.000 => pago 0, arrastre
               500.000; P4 4.000.000/500.000 => pago 3.000.000, arrastre
               0. prior_balance/carry_balance por fila;
               totals = sumas de columnas de PERIODOS con la clave
               LITERAL 'deductable' (8.900.000 / 4.000.000 / 4.900.000)
               y final_balance = arrastre remanente (0.0). Evento con
               fecha de causacion 2028 => meta.out_of_year_events = 1, excluido.
     AC-BE10-5 (catalogo): POST duplicado (year,no) => 400 LITERAL
               "Period {no} already exists for year {year}"; date_to <
               date_from => 422; period_no 99 / year 1999 => 422; PUT
               re-parent => 400 literal; PUT re-save propio => 200
               idempotente; PUT inexistente => 404 "IvaPeriod {id} not
               found"; DELETE => {"deleted_id": n} y repetido => 404;
               GET /?year= filtra y ordena.
     AC-BE10-6 (sin calendario): settlement 200 con periods: [], todo
               en unassigned con sumas correctas y el warning LITERAL
               "No IVA calendar for 2029; configure /budget/iva-period".
               Escenario sin lineas => 200 todo en ceros con los 6
               periods del calendario presentes (§5.9). 404 "Budget
               {id} not found"; year=1999 => 422.
     AC-BE10-7 (gastos e ingresos): fijo 1.000.000 has_iva=False =>
               CERO E2; True/NULL => 190.000 c/u en su payment_date (P2
               fixed 380.000, NULL≡True D-S10-3); ingreso 10.000.000 =>
               E1 1.900.000 en fecha de recaudo; variable_receivables
               8% con base 500.000.000 gravada => E4 = 19% ×
               40.000.000 = 7.600.000 (paridad exacta con la base
               legacy B2/02_02 §6 — se liquida en 2044, año sin AR real
               en la dev: la base es solo el ingreso del propio
               escenario); variable_sales 8% × 12.500.000 => 190.000.
     AC-BE10-8 (regresion): los smokes existentes de planning/lines/
               purchases/internment se corren aparte tras este (unica
               superficie nueva: clave aditiva has_iva en respuestas de
               linea y columna ETL opcional; NINGUNA asercion existente
               compara sets exactos de claves de linea => cero ajustes
               esperados, documentado como nota §10 estilo 02_19). El
               carryover no toca has_iva (D-S10-12).
     NFR-BE10-1/2: durante settlement() NO se emite ningun DML (listener
               SQLAlchemy: 0 INSERT/UPDATE/DELETE) y el conteo de SELECT
               es constante (6 con rate resuelto, 5 sin compras con
               Linea) <= 8, independiente del numero de lineas.
     NFR-BE10-5: evidencia create_all (iva_periods existe) + ALTER
               manual aplicado (budget_lines.has_iva boolean, §10).

Banco de pruebas: 3 Lineas desechables ('SMOKE IVA A'..'C', ids max+1 —
secuencias desincronizadas por el seed historico, nota del purchases
smoke), 3 CECOS '998720'..'998722' y escenarios 'IVA *' sembrados en los
anios 2027/2029/2031/2044/2045/2046/2047. EL SWEEP BORRA SOLO POR
NOMBRE/CODIGO/MARCA y por el SET CERRADO de anios de iva_periods que
este smoke siembra (tabla NUEVA: este smoke es el unico productor de
calendario en la dev; los budgets 2026/2027 REALES del proyecto jamas
se tocan por anio). Pre-clean y post-clean GARANTIZADOS (try/finally)
con verificacion de 0 restos.

Uso:
    1. docker compose -f docker-compose-dev.yaml up   (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD
    3. python test/test_budget_iva_smoke.py           (desde crm_backend/)
       — la seccion unit exige el interprete con las deps del backend
       (venv_backend/Scripts/python.exe), porque importa app.* en el
       proceso con env vars sintetizadas hacia la BD dev de .env_test.
    Tambien coleccionable por pytest via test_budget_iva_smoke_e2e()
    (python -m pytest test/test_budget_iva_smoke.py -x -q).
"""

import sys
import traceback
from datetime import date
from io import BytesIO
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

MARK = "IVA "             # prefijo de aislamiento de nombres de budgets
LINE_MARK = "SMOKE IVA"   # prefijo de aislamiento de line_name
CC_CODES = ("998720", "998721", "998722")
YEAR = 2027               # anio AC-BE10-3/4 (calendario bimestral seed)
NOCAL_YEAR = 2029         # anio AC-BE10-6 (SIN calendario)
CAT_YEAR = 2031           # anio CRUD catalogo (AC-BE10-5)
FLAGS_YEAR = 2044         # anio AC-BE10-7 (variables; 0 AR real dev)
LM_YEAR = 2045            # anio AC-BE10-2 (line manager)
ETL_YEAR1 = 2046          # planning upload 3 archivos sin columna
ETL_YEAR2 = 2047          # legacy expense upload con columna Con IVA
CAL_YEARS = (YEAR, NOCAL_YEAR, CAT_YEAR, FLAGS_YEAR, LM_YEAR,
             ETL_YEAR1, ETL_YEAR2)  # set CERRADO barreable
TOL = 0.01                # tolerancia COP para montos derivados /0.19

# Literales exactos del contrato (spec backend.02_20 §4.4/§5.8/§5.9 —
# citados por los criterios de aceptacion, ganan sobre cualquier helper).
PERIOD_DUP_TPL = "Period {} already exists for year {}"
PERIOD_NF_TPL = "IvaPeriod {} not found"
BUDGET_NF_TPL = "Budget {} not found"
NO_CAL_TPL = "No IVA calendar for {}; configure /budget/iva-period"

# Fixture AC-BE10-3: compra 10.000.000, %int .10, int +15@.6/+45@.4.
PUR_TOTAL = 10_000_000.0
E5_WITH = 1_727_272.73          # T x Total/(1+.10)
E6_1 = 103_636.36               # T x costoInt x .6  (+15 d => 2027-01-25)
E6_2 = 69_090.91                # T x costoInt x .4  (+45 d => 2027-02-24)
E5_NO_PCT = 1_900_000.00        # T x Total sin %int (ancla)


def net_of(iva):
    """Neto que produce el IVA redondo del spec (round(2) absorbe el
    epsilon binario de /0.19; TOL=0.01 en las comparaciones)."""
    return iva / 0.19


state = type("S", (), {})()
state.headers = {}
state.token = None
state.lines = {}            # letter -> id_line (A rate+terms, B sin rate, C lm)
state.ccs = {}              # letter -> id_cost_center
state.b_pur = None          # 2027 AC-BE10-3
state.b_rec = None          # 2027 AC-BE10-4
state.b_flags = None        # 2044 AC-BE10-7
state.b_lm = None           # 2045 AC-BE10-2
state.b_nocal = None        # 2029 AC-BE10-6
state.b_empty = None        # 2027 sin lineas (§5.9)
state.etl_plan = None       # 2046 planning upload (sin columna)
state.etl_exp = None        # 2047 legacy expense upload (con columna)
state.flags_ids = {}        # id_budget_line por etiqueta del t08
state.total = 0
state.passed = 0
state.failed = 0
state.results = []

# ══════════════════════════════════════════════════════════════
# UTILIDADES (mismos patrones de test_budget_internment_smoke.py)
# ══════════════════════════════════════════════════════════════

def api(method, endpoint, auth=True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = dict(state.headers) if auth else {}
    headers.update(kwargs.pop("headers", {}))
    try:
        return requests.request(method, url, headers=headers, timeout=120,
                                **kwargs)
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Request exception: {type(e).__name__}: {str(e)[:100]}")
        return None


def ck(name, ok, detail=""):
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


def approx(a, b, tol=TOL):
    return (a is not None and b is not None
            and abs(float(a) - float(b)) <= tol)


def money_close(d, expected):
    """Claves->valores float de un dict de respuesta, con TOL."""
    return (set(d) == set(expected)
            and all(approx(d[k], v) for k, v in expected.items()))


def run_sql(sql, fetch=False):
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
    # -P null=@NULL@: sin psycopg2 el fallback psql -tA imprimia NULL como
    # cadena VACIA (indistinguible de '' legitimo); con el centinela se
    # mapea NULL -> None, replicando el comportamiento de psycopg2.
    import subprocess
    cmd = ["docker", "exec", PG_DOCKER, "psql", "-U", PG_USER, "-d", PG_DB,
           "-P", "null=@NULL@", "-tAc", sql]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"psql fallo: {out.stderr.strip()[:200]}")
    if not fetch:
        return None
    lines = [l for l in out.stdout.splitlines() if l.strip() != ""]
    return [tuple(None if f == "@NULL@" else f for f in l.split("|"))
            for l in lines]


def sql_scalar(sql):
    rows = run_sql(sql, fetch=True)
    return rows[0][0] if rows else None


def insert_budget(name, year, status_kind="draft"):
    return int(sql_scalar(
        "INSERT INTO budgets (budget_name, budget_year, budget_period, status)"
        f" VALUES ('{name}', {year}, 'ANUAL', '{status_kind}') "
        "RETURNING id_budget"))


def insert_line(budget_id, cc, ltype, bdate, pdate, amount, desc,
                behavior="FIXED", rate=None, has_iva="NULL"):
    """has_iva: 'TRUE' / 'FALSE' / 'NULL' (literal SQL sin comillas)."""
    p = f"'{pdate}'" if pdate else "NULL"
    r = str(rate) if rate is not None else "NULL"
    return int(sql_scalar(
        "INSERT INTO budget_lines (id_budget, id_cost_center, line_type, "
        "budget_date, payment_date, projected_amount, description, "
        "behavior_type, variable_rate, has_iva) VALUES "
        f"({budget_id}, {cc}, '{ltype}', '{bdate}', {p}, {amount}, "
        f"'{desc}', '{behavior}', {r}, {has_iva}) RETURNING id_budget_line"))


def settle(budget_id, year=None):
    params = {"year": year} if year is not None else {}
    r = api("GET", f"/budget/iva/settlement/{budget_id}", params=params)
    return r.json() if r is not None and r.status_code == 200 else None


def settle_raw(budget_id, **params):
    return api("GET", f"/budget/iva/settlement/{budget_id}", params=params)


def period_row(resp, period_no):
    return next((p for p in resp["periods"] if p["period_no"] == period_no),
                None)


def detail_lines(budget_id):
    r = api("GET", f"/budget/planning/{budget_id}/detail")
    if r is None or r.status_code != 200:
        return None
    return {l["id_budget_line"]: l for l in r.json()["budget_lines"]}


def post_period(body):
    return api("POST", "/budget/iva-period/", json=body)


def bimestral_calendar(year, count=6):
    """Siembra N bimestres de `year` via API (P1 ene-feb vence
    {year}-05-21, patron literal del stakeholder AC-BE10-4). True si
    todos 201."""
    months = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)][:count]
    leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    feb_day = 29 if leap else 28
    ends = {1: 31, 2: feb_day, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    ok = True
    for i, (m1, m2) in enumerate(months, start=1):
        due_m, due_y = 2 * i + 3, year
        if due_m > 12:
            due_m -= 12
            due_y += 1
        r = post_period({
            "period_year": year, "period_no": i,
            "date_from": f"{year}-{m1:02d}-01",
            "date_to": f"{year}-{m2:02d}-{ends[m2]:02d}",
            "payment_due_date": f"{due_y}-{due_m:02d}-21",
            "description": None,
        })
        ok = ok and r is not None and r.status_code == 201
    return ok


# Excel builder in-memory (layout real SIIGO: 7 filas decorativas, header
# en fila 8, datos desde fila 9 — skiprows=7 de los tres procesos ETL).
EXPENSE_HEADER = ["Centro de Costo", "Fecha del Gasto (Proyectada)",
                  "Fecha de Pago (Proyectada)", "Concepto del Gasto",
                  "Temporada", "Comportamiento", "Monto o Tasa Solicitado",
                  "Con IVA"]
INCOME_HEADER = ["Centro de Costo", "Fecha de la Facturacion (Proyectada)",
                 "Temporada", "Monto", "Observaciones Adicionales"]
PURCHASE_HEADER = ["Centro de Costo", "Nombre del Colaborador",
                   "Fecha de Solicitud", "Fecha Importacion", "Temporada",
                   "Monto", "Descripcion"]
XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")


def make_xlsx(header, rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for i in range(7):  # bloque decorativo SIIGO (filas 1-7)
        ws.append([f"row{i + 1}"])
    ws.append(header)
    for row in rows:
        ws.append(row)
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


# ══════════════════════════════════════════════════════════════
# LIMPIEZA (pre/post garantizados) — SOLO por marca/nombre/codigo y el
# set CERRADO de anos de calendario que este smoke siembra.
# ══════════════════════════════════════════════════════════════

def sweep():
    run_sql("DELETE FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_name LIKE '{MARK}%')")
    run_sql(f"DELETE FROM budgets WHERE budget_name LIKE '{MARK}%'")
    run_sql("DELETE FROM line_internment_terms WHERE id_line IN "
            f"(SELECT id_line FROM lines WHERE line_name LIKE '{LINE_MARK}%')")
    run_sql("DELETE FROM line_internment_rates WHERE id_line IN "
            f"(SELECT id_line FROM lines WHERE line_name LIKE '{LINE_MARK}%')")
    run_sql("DELETE FROM cost_centers WHERE cost_center_code IN "
            f"{tuple(CC_CODES)}")
    run_sql(f"DELETE FROM lines WHERE line_name LIKE '{LINE_MARK}%'")
    run_sql("DELETE FROM iva_periods WHERE period_year IN "
            f"{tuple(CAL_YEARS)}")


def preclean():
    try:
        sweep()
    except Exception:
        traceback.print_exc()


def postclean():
    try:
        sweep()
        rest_b = int(sql_scalar(
            f"SELECT count(*) FROM budgets WHERE budget_name LIKE '{MARK}%'"))
        rest_cc = int(sql_scalar(
            "SELECT count(*) FROM cost_centers WHERE cost_center_code IN "
            f"{tuple(CC_CODES)}"))
        rest_ln = int(sql_scalar(
            f"SELECT count(*) FROM lines WHERE line_name LIKE '{LINE_MARK}%'"))
        rest_cal = int(sql_scalar(
            "SELECT count(*) FROM iva_periods WHERE period_year IN "
            f"{tuple(CAL_YEARS)}"))
        return ck("Limpieza garantizada: 0 restos (budgets/CECO/Lineas/"
                  "catalogos/calendario)",
                  rest_b == 0 and rest_cc == 0 and rest_ln == 0
                  and rest_cal == 0,
                  f"budgets={rest_b} ceco={rest_cc} lines={rest_ln} "
                  f"cal={rest_cal}")
    except Exception:
        traceback.print_exc()
        return False


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


def _insert_line_id(name):
    return int(sql_scalar(
        "INSERT INTO lines (id_line, line_name) VALUES "
        "((SELECT max(id_line) + 1 FROM lines), "
        f"'{LINE_MARK} {name}') RETURNING id_line"))


def _insert_cc(code, name, id_line):
    lin = str(id_line) if id_line is not None else "NULL"
    return int(sql_scalar(
        "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
        "cost_center_name, is_active, description, id_line) VALUES "
        "((SELECT max(id_cost_center) + 1 FROM cost_centers), "
        f"'{code}', '{name}', true, 'BE-S10 smoke: {name}', {lin}) "
        "RETURNING id_cost_center"))


def t02_setup_fixtures():
    """NFR-BE10-5: iva_periods existe (create_all, 0 DDL) y
    budget_lines.has_iva es boolean (ALTER de §10 ya aplicado). Linea A
    con rate .10 + terminos int VIA API; calendarios bimestrales 2027(6)
    /2044(4)/2045(3)."""
    tab = int(sql_scalar(
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name='iva_periods'"))
    col = sql_scalar(
        "SELECT data_type FROM information_schema.columns WHERE "
        "table_name='budget_lines' AND column_name='has_iva'")
    ck("NFR-BE10-5/§10: create_all creo iva_periods y el ALTER manual "
       "anadio budget_lines.has_iva boolean",
       tab == 1 and col == "boolean", f"tab={tab} col={col}")

    for letter in "ABC":
        state.lines[letter] = _insert_line_id(letter)
    for i, letter in enumerate("ABC"):
        state.ccs[letter] = _insert_cc(CC_CODES[i], f"{LINE_MARK} cc{letter}",
                                       state.lines[letter])
    ck("Setup: 3 Lineas + 3 CECOS desechables (max+1: secuencias "
       "desincronizadas, nota purchases smoke)",
       len(state.lines) == 3 and len(state.ccs) == 3)

    ok = True
    r = api("POST", "/budget/line-internment-rate/",
            json={"id_line": state.lines["A"], "internment_pct": 0.10})
    ok = ok and r is not None and r.status_code == 201
    for spec in ((15, 0.6), (45, 0.4)):
        rt = api("POST", "/budget/line-internment-term/",
                 json={"id_line": state.lines["A"],
                       "payment_days": spec[0], "payment_pct": spec[1]})
        ok = ok and rt is not None and rt.status_code == 201
    ck("Setup: Linea A con rate .10 e int-terminos +15@.6/+45@.4 via API "
       "(B y C quedan SIN rate => degradacion D-S10-8)", ok,
       (r.text[:100] if r is not None else "error"))

    ok_cal = (bimestral_calendar(YEAR)
              and bimestral_calendar(FLAGS_YEAR, 4)
              and bimestral_calendar(LM_YEAR, 3))
    return ck("Setup: calendarios bimestrales 2027 (6, P1 vence "
              "2027-05-21), 2044 (4) y 2045 (3) via POST "
              "/budget/iva-period", ok_cal)


def t03_seed_scenarios():
    """Escenarios 'IVA *' sembrados por SQL con control fino de has_iva
    (TRUE/FALSE/NULL) y las bases de la recurrencia AC-BE10-4 (netos
    iva/0.19 cuyo round(2) reproduce los redondos del spec)."""
    state.b_pur = insert_budget(MARK + "pur 2027", YEAR)
    insert_line(state.b_pur, state.ccs["A"], "PURCHASE", "2027-01-10",
                None, PUR_TOTAL, "BE10 compra A 10M pct.10")
    insert_line(state.b_pur, state.ccs["B"], "PURCHASE", "2027-01-20",
                None, PUR_TOTAL, "BE10 compra B 10M sin pct")

    state.b_rec = insert_budget(MARK + "rec 2027", YEAR)
    insert_line(state.b_rec, state.ccs["C"], "INCOME", "2027-01-10",
                "2027-01-15", 10_000_000, "BE10 rec P1 gen 1.9M")
    insert_line(state.b_rec, state.ccs["C"], "EXPENSE", "2027-03-01",
                "2027-03-15", net_of(2_500_000), "BE10 rec P2 desc 2.5M",
                has_iva="TRUE")
    insert_line(state.b_rec, state.ccs["C"], "INCOME", "2027-05-01",
                "2027-05-15", net_of(3_000_000), "BE10 rec P3 gen 3M")
    insert_line(state.b_rec, state.ccs["C"], "EXPENSE", "2027-06-01",
                "2027-06-15", net_of(1_000_000), "BE10 rec P3 desc 1M",
                has_iva="TRUE")
    insert_line(state.b_rec, state.ccs["C"], "INCOME", "2027-07-01",
                "2027-07-20", net_of(4_000_000), "BE10 rec P4 gen 4M")
    insert_line(state.b_rec, state.ccs["C"], "EXPENSE", "2027-08-01",
                "2027-08-20", net_of(500_000), "BE10 rec P4 desc 0.5M",
                has_iva="TRUE")
    insert_line(state.b_rec, state.ccs["C"], "INCOME", "2028-02-02",
                "2028-02-02", 1_000_000, "BE10 rec out-of-year 2028")

    state.b_flags = insert_budget(MARK + "flags 2044", FLAGS_YEAR)
    insert_line(state.b_flags, state.ccs["C"], "INCOME", "2044-01-10",
                "2044-01-20", 10_000_000, "BE10 E1 10M")
    insert_line(state.b_flags, state.ccs["C"], "EXPENSE", "2044-02-01",
                "2044-02-05", 1_000_000, "BE10 fijo has_iva FALSE",
                has_iva="FALSE")
    insert_line(state.b_flags, state.ccs["C"], "EXPENSE", "2044-03-01",
                "2044-03-05", 1_000_000, "BE10 fijo has_iva TRUE",
                has_iva="TRUE")
    insert_line(state.b_flags, state.ccs["C"], "EXPENSE", "2044-04-01",
                "2044-04-05", 1_000_000, "BE10 fijo has_iva NULL",
                has_iva="NULL")
    insert_line(state.b_flags, state.ccs["C"], "INCOME", "2044-05-10",
                "2044-05-10", 500_000_000, "BE10 base E4 500M")
    insert_line(state.b_flags, state.ccs["C"], "EXPENSE", "2044-05-10",
                None, 0, "BE10 var_rec 8pct",
                behavior="VARIABLE_RECEIVABLES", rate=0.08, has_iva="TRUE")
    insert_line(state.b_flags, state.ccs["C"], "INCOME", "2044-06-10",
                "2044-06-10", 12_500_000, "BE10 base E3 12.5M")
    insert_line(state.b_flags, state.ccs["C"], "EXPENSE", "2044-06-05",
                None, 0, "BE10 var_sales 8pct",
                behavior="VARIABLE_SALES", rate=0.08, has_iva="NULL")

    state.b_nocal = insert_budget(MARK + "nocal 2029", NOCAL_YEAR)
    insert_line(state.b_nocal, state.ccs["C"], "INCOME", "2029-03-01",
                "2029-03-10", 10_000_000, "BE10 sin calendario")
    state.b_empty = insert_budget(MARK + "empty 2027", YEAR)
    return ck("Fixture: 6 escenarios sembrados (pur/rec/flags/nocal/empty "
              "+ lm via API en t10)", True)


def t04_ac_be10_3_purchase_events():
    """AC-BE10-3 (nivel HTTP): settlement(b_pur) P1 con import_vat
    3.627.272,73 (E5 A + E5 B sin pct) + nationalization_vat 172.727,27
    (E6 .6+.4 caen ambos en ene-feb), events_count 4 y arrastre final
    3.800.000 ilimitado (escenario puro descontable, D-S10-11)."""
    resp = settle(state.b_pur)
    if resp is None:
        return ck("AC-BE10-3 settlement(b_pur) 200", False)
    p1 = period_row(resp, 1)
    ck("AC-BE10-3 P1 generated.ventas 0.0 y deductible.import_vat "
       "3.627.272,73 (E5 1.727.272,73 + E5-sin-pct 1.900.000,00)",
       p1 is not None and approx(p1["generated"]["ventas"], 0.0)
       and approx(p1["deductible"]["import_vat"], 3_627_272.73),
       str(p1["deductible"]) if p1 else "")
    ck("AC-BE10-3 P1 nationalization_vat 172.727,27 (103.636,36 + "
       "69.090,91) y fixed/variable en 0.0",
       p1 is not None
       and approx(p1["deductible"]["nationalization_vat"], 172_727.27)
       and approx(p1["deductible"]["fixed_expenses"], 0.0)
       and approx(p1["deductible"]["variable_expenses"], 0.0))
    ck("AC-BE10-3 P1 events_count 4, pago 0 (descontable puro), base "
       "-3.800.000 y arrastre 3.800.000 (SIGMA compra A = T x Total = "
       "1.900.000 exacto + 1.900.000 compra B)",
       p1 is not None and p1["events_count"] == 4
       and approx(p1["payment"], 0.0)
       and approx(p1["tax_base"], -3_800_000.0)
       and approx(p1["carry_balance"], 3_800_000.0))
    ck("AC-BE10-3/D-S10-11: el saldo a favor 3.800.000 arrastra SIN "
       "limite por los 5 periodos siguientes (prior/carry) y "
       "totals.final_balance lo reporta",
       all(period_row(resp, n) is not None
           and approx(period_row(resp, n)["prior_balance"], 3_800_000.0)
           and approx(period_row(resp, n)["carry_balance"], 3_800_000.0)
           for n in range(2, 7))
       and approx(resp["totals"]["final_balance"], 3_800_000.0))
    ck("§4.6 contrato: year default = budget_year (2027), tax_rate_used "
       "0.19, basis 'accrual', sin warnings ni out-of-year, unassigned "
       "0/0/0 y filters eco",
       resp["year"] == YEAR and resp["tax_rate_used"] == 0.19
       and resp["basis"] == "accrual" and resp["meta"]["warnings"] == []
       and resp["meta"]["out_of_year_events"] == 0
       and resp["unassigned"] == {"generated": 0.0, "deductible": 0.0,
                                  "events_count": 0}
       and resp["meta"]["filters"] == {"id_budget": state.b_pur,
                                       "year": YEAR})
    return True


def t05_ac_be10_4_recurrence():
    """AC-BE10-4 con los NUMERALES EXACTOS del spec (pago 1.9M /
    arrastre 2.5M / 500k / pago 3.0M / arrastre 0)."""
    resp = settle(state.b_rec)
    if resp is None:
        return ck("AC-BE10-4 settlement(b_rec) 200", False)
    p1 = period_row(resp, 1)
    ok1 = (p1 and money_close(p1["generated"], {"ventas": 1_900_000.0})
           and all(v == 0.0 for v in p1["deductible"].values())
           and approx(p1["prior_balance"], 0.0)
           and approx(p1["tax_base"], 1_900_000.0)
           and approx(p1["payment"], 1_900_000.0)
           and approx(p1["carry_balance"], 0.0))
    ck("AC-BE10-4 P1 1.900.000/0 => pago 1.900.000, arrastre 0 "
       "(rango ene-feb y vencimiento 2027-05-21 literales)",
       ok1 and p1["payment_due_date"] == "2027-05-21"
       and p1["date_from"] == "2027-01-01"
       and p1["date_to"] == "2027-02-28")
    p2 = period_row(resp, 2)
    ok2 = (p2 and approx(p2["generated"]["ventas"], 0.0)
           and approx(p2["deductible"]["fixed_expenses"], 2_500_000.0)
           and approx(p2["prior_balance"], 0.0)
           and approx(p2["tax_base"], -2_500_000.0)
           and approx(p2["payment"], 0.0)
           and approx(p2["carry_balance"], 2_500_000.0))
    ck("AC-BE10-4 P2 0/2.500.000 => pago 0, arrastre 2.500.000 "
       "(E2 fijo por neto iva/0.19)", ok2)
    p3 = period_row(resp, 3)
    ok3 = (p3 and approx(p3["generated"]["ventas"], 3_000_000.0)
           and approx(p3["deductible"]["fixed_expenses"], 1_000_000.0)
           and approx(p3["prior_balance"], 2_500_000.0)
           and approx(p3["tax_base"], -500_000.0)
           and approx(p3["payment"], 0.0)
           and approx(p3["carry_balance"], 500_000.0))
    ck("AC-BE10-4 P3 3.000.000/1.000.000 con prior 2.500.000 => base "
       "-500.000 => pago 0, arrastre 500.000", ok3)
    p4 = period_row(resp, 4)
    ok4 = (p4 and approx(p4["generated"]["ventas"], 4_000_000.0)
           and approx(p4["deductible"]["fixed_expenses"], 500_000.0)
           and approx(p4["prior_balance"], 500_000.0)
           and approx(p4["tax_base"], 3_000_000.0)
           and approx(p4["payment"], 3_000_000.0)
           and approx(p4["carry_balance"], 0.0))
    ck("AC-BE10-4 P4 4.000.000/500.000 con prior 500.000 => pago "
       "3.000.000, arrastre 0", ok4)
    ck("AC-BE10-4 totals: sumas de columnas de PERIODOS con la clave "
       "LITERAL 'deductable' y final_balance = arrastre remanente (0)",
       set(resp["totals"]) == {"generated", "deductable", "payments",
                               "final_balance"}
       and money_close(resp["totals"],
                       {"generated": 8_900_000.0,
                        "deductable": 4_000_000.0,
                        "payments": 4_900_000.0, "final_balance": 0.0}))
    ck("§4.4: el evento con fecha de causación 2028-02-02 NO liquida "
       "=> meta.out_of_year_events=1; unassigned 0 (calendario 2027 "
       "cubre todo el anio)",
       resp["meta"]["out_of_year_events"] == 1
       and resp["unassigned"]["events_count"] == 0)
    return ok1 and ok2 and ok3 and ok4


def t06_ac_be10_5_catalog():
    """AC-BE10-5: los literales/verbos del catalogo sobre CAT_YEAR."""
    base = {"period_year": CAT_YEAR, "period_no": 1,
            "date_from": f"{CAT_YEAR}-01-01", "date_to": f"{CAT_YEAR}-02-28",
            "payment_due_date": f"{CAT_YEAR}-05-21", "description": None}
    r1 = post_period(base)
    ok = r1 is not None and r1.status_code == 201
    ck("AC-BE10-5 POST valido -> 201 eco", ok,
       (r1.text[:110] if r1 is not None else "error"))
    if not ok:
        return False
    id1 = r1.json()["id_iva_period"]
    r2 = post_period(base)
    ck("AC-BE10-5 POST duplicado (year,no) -> 400 LITERAL \"Period 1 "
       "already exists for year 2031\" (guard CRUD antes del "
       "IntegrityError)",
       r2 is not None and r2.status_code == 400
       and r2.json().get("detail") == PERIOD_DUP_TPL.format(1, CAT_YEAR),
       (r2.text[:110] if r2 is not None else "error"))
    r3 = post_period(dict(base, period_no=2, date_from="2031-03-01",
                          date_to="2031-01-15"))
    ck("AC-BE10-5 date_to < date_from -> 422 (model_validator)",
       r3 is not None and r3.status_code == 422,
       (str(r3.status_code) if r3 is not None else "err"))
    r4 = post_period(dict(base, period_no=99))
    r5 = post_period(dict(base, period_year=1999, period_no=5))
    ck("AC-BE10-5 period_no 99 -> 422 (ge=1 le=36) y period_year 1999 "
       "-> 422 (ge=2000 le=2100)",
       r4 is not None and r4.status_code == 422
       and r5 is not None and r5.status_code == 422)
    r6 = post_period(dict(base, period_no=2, date_from="2031-03-01",
                          date_to="2031-04-30",
                          payment_due_date="2031-07-21"))
    ok6 = r6 is not None and r6.status_code == 201
    id2 = r6.json()["id_iva_period"] if ok6 else None
    r7 = api("PUT", f"/budget/iva-period/{id1}", json=dict(base,
                                                           period_no=2))
    ck("AC-BE10-5 PUT re-parent a (year,no) ajena -> 400 mismo literal",
       ok6 and r7 is not None and r7.status_code == 400
       and r7.json().get("detail") == PERIOD_DUP_TPL.format(2, CAT_YEAR),
       (r7.text[:110] if r7 is not None else "error"))
    r8 = api("PUT", f"/budget/iva-period/{id1}",
             json=dict(base, description="re-saved"))
    ck("AC-BE10-5 PUT re-save de la propia (year,no) -> 200 idempotente "
       "(full replacement, no colisiona consigo misma)",
       r8 is not None and r8.status_code == 200
       and r8.json().get("description") == "re-saved"
       and r8.json().get("period_no") == 1)
    r9 = api("PUT", "/budget/iva-period/99999999",
             json=dict(base, period_no=7))
    ck("AC-BE10-5 PUT inexistente -> 404 LITERAL \"IvaPeriod 99999999 "
       "not found\"",
       r9 is not None and r9.status_code == 404
       and r9.json().get("detail") == PERIOD_NF_TPL.format(99999999),
       (r9.text[:110] if r9 is not None else "error"))
    r10 = api("GET", "/budget/iva-period/", params={"year": CAT_YEAR})
    ck("AC-BE10-5 GET /?year=2031 filtra y ordena por period_no",
       r10 is not None and r10.status_code == 200
       and [p["period_no"] for p in r10.json()] == [1, 2],
       (r10.text[:110] if r10 is not None else "error"))
    rd1 = api("DELETE", f"/budget/iva-period/{id1}")
    rd2 = api("DELETE", f"/budget/iva-period/{id2}")
    ck("AC-BE10-5 DELETE -> {\"deleted_id\": n} (x2)",
       rd1 is not None and rd1.json() == {"deleted_id": id1}
       and rd2 is not None and rd2.json() == {"deleted_id": id2},
       (rd1.text[:60] if rd1 is not None else "error"))
    r11 = api("GET", "/budget/iva-period/", params={"year": CAT_YEAR})
    r12 = api("DELETE", f"/budget/iva-period/{id1}")
    return ck("AC-BE10-5 GET del anio barrido -> [] y DELETE repetido -> "
              "404 mismo literal",
              r11 is not None and r11.json() == []
              and r12 is not None and r12.status_code == 404
              and r12.json().get("detail") == PERIOD_NF_TPL.format(id1))


def t07_ac_be10_6_no_calendar():
    """AC-BE10-6: sin calendario => 200 periods:[] + TODO unassigned +
    warning LITERAL. Escenario sin lineas => 200 ceros con periods del
    calendario (§5.9). 404/422 del endpoint."""
    resp = settle(state.b_nocal)
    if resp is None:
        return ck("AC-BE10-6 settlement(2029) 200", False)
    ck("AC-BE10-6 periods: [] y TODO en unassigned con sumas correctas "
       "(1.900.000 generado, 0 descontable, 1 evento; totals aparte 0)",
       resp["periods"] == [] and resp["year"] == NOCAL_YEAR
       and approx(resp["unassigned"]["generated"], 1_900_000.0)
       and approx(resp["unassigned"]["deductible"], 0.0)
       and resp["unassigned"]["events_count"] == 1
       and resp["totals"] == {"generated": 0.0, "deductable": 0.0,
                              "payments": 0.0, "final_balance": 0.0})
    ck("AC-BE10-6/§4.4 warning LITERAL \"No IVA calendar for 2029; "
       "configure /budget/iva-period\" (NFR-BE10-3: nunca 500/422)",
       resp["meta"]["warnings"] == [NO_CAL_TPL.format(NOCAL_YEAR)],
       str(resp["meta"]["warnings"]))
    empty = settle(state.b_empty)
    ck("§5.9 escenario SIN lineas -> 200 todo en ceros con los 6 periods "
       "del calendario presentes (events_count 0, desgloses 0.0)",
       empty is not None and len(empty["periods"]) == 6
       and all(p["events_count"] == 0 and approx(p["payment"], 0.0)
               and p["generated"] == {"ventas": 0.0}
               and money_close(p["deductible"],
                               {"fixed_expenses": 0.0,
                                "variable_expenses": 0.0,
                                "import_vat": 0.0,
                                "nationalization_vat": 0.0})
               for p in empty["periods"])
       and empty["meta"]["warnings"] == [])
    r404 = settle_raw(99999999)
    r422 = settle_raw(state.b_nocal, year=1999)
    return ck("§5.9 budget inexistente -> 404 \"Budget 99999999 not "
              "found\" (CRUD Optional->None) y ?year=1999 -> 422",
              r404 is not None and r404.status_code == 404
              and r404.json().get("detail") == BUDGET_NF_TPL.format(99999999)
              and r422 is not None and r422.status_code == 422,
              (f"{r404.status_code if r404 is not None else 'err'}/"
               f"{r422.status_code if r422 is not None else 'err'}"))


def t08_ac_be10_7_flags_and_bases():
    """AC-BE10-7 sobre b_flags (2044): fijo False => 0 E2; True/NULL =>
    190.000 c/u; ingreso => 1.900.000 E1; E4 = 19% x 40M y E3 = 190k."""
    resp = settle(state.b_flags)
    if resp is None:
        return ck("AC-BE10-7 settlement(b_flags) 200", False)
    lines = detail_lines(state.b_flags) or {}
    if not lines:
        return ck("AC-BE10-7 detail legible", False)
    by_desc = {l["description"]: l for l in lines.values()}
    l_false = by_desc["BE10 fijo has_iva FALSE"]["id_budget_line"]
    l_true = by_desc["BE10 fijo has_iva TRUE"]["id_budget_line"]
    l_null = by_desc["BE10 fijo has_iva NULL"]["id_budget_line"]
    l_vr = by_desc["BE10 var_rec 8pct"]["id_budget_line"]
    l_vs = by_desc["BE10 var_sales 8pct"]["id_budget_line"]
    state.flags_ids = dict(false=l_false, true=l_true, null=l_null,
                           vr=l_vr, vs=l_vs)
    p1 = period_row(resp, 1)
    ck("AC-BE10-7 gasto fijo 1.000.000 has_iva=False => CERO E2 (P1 "
       "fixed_expenses 0.0 y events_count 1: solo el ingreso — no se "
       "emite 0)",
       p1 is not None and approx(p1["deductible"]["fixed_expenses"], 0.0)
       and p1["events_count"] == 1)
    ck("AC-BE10-7 ingreso 10.000.000 => E1 1.900.000 en su fecha de "
       "recaudo (P1 ene-feb)",
       p1 is not None and approx(p1["generated"]["ventas"],
                                 1_900_000.0))
    p2 = period_row(resp, 2)
    ck("AC-BE10-7/D-S10-3 fijos True y NULL(≡True) 1.000.000 c/u => P2 "
       "fixed_expenses 380.000 (2×190.000) y events_count 2",
       p2 is not None
       and approx(p2["deductible"]["fixed_expenses"], 380_000.0)
       and p2["events_count"] == 2)
    p3 = period_row(resp, 3)
    ck("AC-BE10-7 variable_receivables 8% con base 500.000.000 gravada "
       "=> E4 = 19% × 40.000.000 = 7.600.000 (+E3 190.000 => P3 "
       "variable_expenses 7.790.000)",
       p3 is not None
       and approx(p3["deductible"]["variable_expenses"], 7_790_000.0))
    ck("AC-BE10-7 P3 ventas 97.375.000 (500M×T + 12,5M×T — los "
       "ingresos SIEMPRE generan)",
       p3 is not None and approx(p3["generated"]["ventas"],
                                 97_375_000.0))
    db_vals = [r[0] for r in run_sql(
        "SELECT has_iva FROM budget_lines WHERE id_budget_line IN "
        f"({l_false},{l_true},{l_null}) ORDER BY id_budget_line",
        fetch=True)]
    ck("AC-BE10-7 persistencia SQL del trio FALSE/TRUE/NULL (NULL ≡ "
       "True SOLO como regla de calculo, sin backfill §3.1)",
       db_vals == [False, True, None], str(db_vals))
    return ck("AC-BE10-7 detail expone has_iva por linea (False/True/"
              "None segun el caso)",
              lines[l_false]["has_iva"] is False
              and lines[l_true]["has_iva"] is True
              and lines[l_null]["has_iva"] is None)


def t09_ac_be10_1_etl():
    """AC-BE10-1: legacy POST /budget/upload/budget-plan-expense CON la
    columna Con IVA (Si/No/sí/X/vacia) y planning upload de 3 archivos
    SIN la columna (los 3 tipos => NULL, AC-REG-01)."""
    cc = CC_CODES[0]  # ccA
    rows = [
        [cc, date(ETL_YEAR2, 1, 10), date(ETL_YEAR2, 1, 20),
         "BE10 etl Si", "", "Fijo", 1_000_000, "Si"],
        [cc, date(ETL_YEAR2, 2, 10), date(ETL_YEAR2, 2, 20),
         "BE10 etl No", "", "Fijo", 1_000_000, "No"],
        [cc, date(ETL_YEAR2, 3, 10), date(ETL_YEAR2, 3, 20),
         "BE10 etl si", "", "Fijo", 1_000_000, "sí"],
        [cc, date(ETL_YEAR2, 4, 10), date(ETL_YEAR2, 4, 20),
         "BE10 etl X", "", "Fijo", 1_000_000, "X"],
        [cc, date(ETL_YEAR2, 5, 10), date(ETL_YEAR2, 5, 20),
         "BE10 etl vacio", "", "Fijo", 1_000_000, None],
    ]
    bio = make_xlsx(EXPENSE_HEADER, rows)
    r = api("POST", "/budget/upload/budget-plan-expense",
            data={"budget_name": MARK + "etl exp 2047",
                  "budget_year": str(ETL_YEAR2), "budget_period": "ANUAL"},
            files={"file": ("gastos_iva.xlsx", bio, XLSX_MIME)})
    # AC-REG-01: el endpoint legacy responde 200 (sin status_code en la
    # ruta — hoy y ayer); se acepta SOLO ese estatus identico a hoy.
    if r is None or r.status_code != 200:
        return ck("AC-BE10-1 legacy upload con columna Con IVA -> 200 "
                  "(identico a hoy, AC-REG-01)",
                  False, (r.text[:140] if r is not None else "error"))
    state.etl_exp = r.json()["id_budget"]
    ck("AC-BE10-1/AC-REG-01: respuesta legacy con las MISMAS claves de "
       "hoy y budget_lines_count 5 (la columna extra no rompe nada)",
       set(r.json()) == {"message", "id_budget", "budget_lines_count"}
       and r.json()["budget_lines_count"] == 5, r.text[:80])
    db_vals = [row[0] for row in run_sql(
        "SELECT has_iva FROM budget_lines WHERE id_budget = "
        f"{state.etl_exp} ORDER BY id_budget_line", fetch=True)]
    exp = [True, False, True, True, None]
    ck("AC-BE10-1 mapeo §5.6 end-to-end: Si(True) No(False) sí(True) "
       "X(True) vacio(None) — persistidos en budget_lines",
       db_vals == exp, f"got={db_vals} exp={exp}")
    det = detail_lines(state.etl_exp)
    ck("AC-BE10-1 el flag sale en GET /{id}/detail (has_iva aditivo por "
       "renglon)", det is not None
       and [det[k]["has_iva"] for k in sorted(det)] == exp,
       str(det if det is not None else None)[:100])

    # Planning upload SIN la columna + income + purchase (3 archivos):
    # los 3 tipos de linea quedan NULL (builders income/purchase NO
    # tocan la columna, §5.5) y la subida es identica a hoy.
    inc = make_xlsx(INCOME_HEADER, [
        [cc, date(ETL_YEAR1, 3, 10), "", 20_000_000, "BE10 plan inc"]])
    exp_noflag = make_xlsx(EXPENSE_HEADER[:-1], [
        [cc, date(ETL_YEAR1, 4, 10), date(ETL_YEAR1, 4, 20),
         "BE10 plan exp", "", "Fijo", 5_000_000]])
    pur = make_xlsx(PURCHASE_HEADER, [
        [cc, "smoke", date(ETL_YEAR1, 5, 2), date(ETL_YEAR1, 5, 1), "",
         8_000_000, "BE10 plan pur"]])
    files = {
        "scenario_name": (None, MARK + "etl plan 2046"),
        "budget_year": (None, str(ETL_YEAR1)),
        "budget_period": (None, "ANUAL"),
        "file_ingresos": ("inc.xlsx", inc, XLSX_MIME),
        "file_gastos": ("exp.xlsx", exp_noflag, XLSX_MIME),
        "file_compras": ("pur.xlsx", pur, XLSX_MIME),
    }
    r2 = api("POST", "/budget/planning/upload", files=files)
    if r2 is None or r2.status_code != 201:
        return ck("AC-BE10-1 planning upload 3 archivos sin columna -> "
                  "201", False, (r2.text[:160] if r2 is not None
                                 else "error"))
    state.etl_plan = r2.json()["id_budget"]
    # NB ORDER BY sobre columna enum PG ordena por orden de declaracion
    # (INCOME, EXPENSE, PURCHASE): se normaliza en Python para comparar.
    vals2 = sorted((str(a), b, int(c)) for a, b, c in run_sql(
        "SELECT line_type, has_iva, count(*) FROM budget_lines WHERE "
        f"id_budget = {state.etl_plan} GROUP BY line_type, has_iva",
        fetch=True))
    return ck("AC-BE10-1 archivo SIN la columna => todas NULL (INCOME, "
              "EXPENSE y PURCHASE: income/purchase builders intactos) y "
              "subida identica a hoy (AC-REG-01: 1+1+1 filas)",
              vals2 == [("EXPENSE", None, 1), ("INCOME", None, 1),
                        ("PURCHASE", None, 1)], str(vals2))


def t10_ac_be10_2_line_manager():
    """AC-BE10-2: POST /line sin campo => True; PUT false => reflejado y
    persistente; PUT omitido => keep; INCOME flag=false persiste pero
    E1 no cambia; PURCHASE flag=false no altera E5 (§3.1)."""
    state.b_lm = insert_budget(MARK + "lm 2045", LM_YEAR)
    r1 = api("POST", f"/budget/planning/{state.b_lm}/line", json={
        "id_cost_center": state.ccs["C"], "line_type": "expense",
        "budget_date": "2045-05-05", "projected_amount": 1_000_000,
        "behavior_type": "fixed", "description": "BE10 lm fijo"})
    ok = (r1 is not None and r1.status_code == 201
          and r1.json().get("has_iva") is True)
    state.lm_fixed = r1.json()["id_budget_line"] if ok else None
    ck("AC-BE10-2 POST /line sin has_iva -> 201 con has_iva TRUE "
       "(§5.4: None => True, no NULL)", ok,
       (r1.text[:110] if r1 is not None else "error"))
    if state.lm_fixed is None:
        return False
    sql1 = sql_scalar("SELECT has_iva FROM budget_lines WHERE "
                      f"id_budget_line = {state.lm_fixed}")
    ck("AC-BE10-2 POST sin campo persiste TRUE en budget_lines",
       sql1 is True, str(sql1))

    r2 = api("PUT", f"/budget/planning/line/{state.lm_fixed}",
             json={"has_iva": False})
    sql2 = sql_scalar("SELECT has_iva FROM budget_lines WHERE "
                      f"id_budget_line = {state.lm_fixed}")
    ck("AC-BE10-2 PUT {has_iva:false} => reflejado en respuesta y "
       "persistente (FALSE en BD)",
       r2 is not None and r2.status_code == 200
       and r2.json().get("has_iva") is False and sql2 is False,
       (r2.text[:110] if r2 is not None else "error"))

    r3 = api("PUT", f"/budget/planning/line/{state.lm_fixed}",
             json={"description": "BE10 lm keep"})
    ck("AC-BE10-2 PUT omitiendo has_iva => KEEP (partial §5.4: None no "
       "toca la columna)",
       r3 is not None and r3.status_code == 200
       and r3.json().get("has_iva") is False
       and r3.json().get("description") == "BE10 lm keep")

    r4 = api("PUT", f"/budget/planning/line/{state.lm_fixed}",
             json={"has_iva": True})
    ck("AC-BE10-2 PUT {has_iva:true} reactiva el descuento",
       r4 is not None and r4.status_code == 200
       and r4.json().get("has_iva") is True)

    ri = api("POST", f"/budget/planning/{state.b_lm}/line", json={
        "id_cost_center": state.ccs["C"], "line_type": "income",
        "budget_date": "2045-01-15", "projected_amount": 10_000_000,
        "behavior_type": "fixed", "has_iva": False,
        "description": "BE10 lm ingreso flag false"})
    state.lm_income = (ri.json()["id_budget_line"]
                       if ri is not None and ri.status_code == 201
                       else None)
    rp = api("POST", f"/budget/planning/{state.b_lm}/line", json={
        "id_cost_center": state.ccs["B"], "line_type": "purchase",
        "budget_date": "2045-03-05", "projected_amount": PUR_TOTAL,
        "behavior_type": "fixed", "description": "BE10 lm compra"})
    state.lm_purchase = (rp.json()["id_budget_line"]
                         if rp is not None and rp.status_code == 201
                         else None)
    ck("AC-BE10-2/§5.2 POST income con has_iva=false se ACEITA y "
       "persiste FALSE (D-S10-5 lo ignora al derivar); POST purchase sin "
       "campo => TRUE",
       state.lm_income is not None and state.lm_purchase is not None
       and ri.json()["has_iva"] is False and rp.json()["has_iva"] is True)

    rpu = api("PUT", f"/budget/planning/line/{state.lm_purchase}",
              json={"has_iva": False})
    resp = settle(state.b_lm)
    p1 = period_row(resp, 1) if resp else None
    p2 = period_row(resp, 2) if resp else None
    p3 = period_row(resp, 3) if resp else None
    ck("AC-BE10-2/§4.3 E1 ignora el flag: INCOME 10M con has_iva=false "
       "=> P1 generado.ventas 1.900.000 igualmente",
       p1 is not None and approx(p1["generated"]["ventas"],
                                 1_900_000.0))
    ck("AC-BE10-2/§3.1 E5 ignora el flag: PUT false a la PURCHASE "
       "devuelve false PERO P2 import_vat sigue 1.900.000 y cero "
       "nationalization_vat (Linea B sin pct)",
       rpu is not None and rpu.json().get("has_iva") is False
       and p2 is not None
       and approx(p2["deductible"]["import_vat"], E5_NO_PCT)
       and approx(p2["deductible"]["nationalization_vat"], 0.0))
    return ck("AC-BE10-2 el fijo re-activado (PUT true) SI descuenta: "
              "P3 fixed_expenses 190.000 (ancla budget_date "
              "2045-05-05, payment_date NULL)",
              p3 is not None
              and approx(p3["deductible"]["fixed_expenses"],
                         190_000.0))


# ══════════════════════════════════════════════════════════════
# SECCION UNIT (in-process, mismo codigo que sirve :8003 via volumen)
# ══════════════════════════════════════════════════════════════

def _unit_modules():
    """Estilo _unit_planning del internment smoke: sintetiza los env vars
    ANTES del import (sin .env en el host) y pre-warmea app.api porque es
    el orden que rompe el ciclo core.auth <-> app.api.utils en el
    arranque real."""
    import os
    root = str(TEST_DIR.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    for key, val in {
        "ENV": "test",
        "POSTGRES_USER": PG_USER, "POSTGRES_PASSWORD": PG_PASSWORD,
        "POSTGRES_DB": PG_DB, "POSTGRES_HOST": PG_HOST,
        "POSTGRES_PORT": str(PG_PORT),
        "SECRET_KEY": "smoke-unit", "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
        "BACKEND_CORS_ORIGINS": "*", "USERNAME": "smoke",
        "CLIENT_ID": "smoke", "CLIENT_SECRET": "smoke",
        "TENANT_ID": "smoke", "FRONTEND_URL": "http://127.0.0.1:5173",
    }.items():
        os.environ[key] = val
    import app.api  # noqa: F401 — pre-warm para romper el import circular
    from app.services.budgetIvaEngine import BudgetIvaEngine
    from app.db import SessionLocal, engine
    return BudgetIvaEngine, SessionLocal, engine


def t11_unit_be10():
    """Checks in-process sobre la misma BD con el fixture vivo: registro
    de eventos AC-BE10-3 EXACTO, degradacion sin pct (D-S10-8), E4 =
    19% × 40M / E3 = 190k y linea False sin evento, paridad
    unit-vs-HTTP del contrato §4.6 (dict-a-dict), determinismo, pureza
    NFR-BE10-1 y economia NFR-BE10-2 MEDIDAS, y tabla de valores §5.6
    del mapeador ETL."""
    try:
        BudgetIvaEngine, SessionLocal, engine = _unit_modules()
    except Exception as e:
        return ck("Unit BE10: import in-process del engine", False,
                  f"{type(e).__name__}: {str(e)[:130]}")
    ck("Unit BE10: app.services.budgetIvaEngine importado in-process "
       "(mismo modulo que sirve :8003 via volumen montado)", True)
    db = SessionLocal()
    try:
        eng = BudgetIvaEngine(db)

        # ── AC-BE10-3: registro EXACTO (fecha, concepto, monto) ──
        evs = eng.events(state.b_pur, YEAR)
        expected = [
            ("2027-01-10", "import_vat", E5_WITH),
            ("2027-01-10", "nationalization_vat", E6_1),
            ("2027-01-10", "nationalization_vat", E6_2),
            ("2027-01-20", "import_vat", E5_NO_PCT),
        ]
        got = [(e["date"], e["concept"], e["amount"]) for e in evs]
        sigma_a = sum(e["amount"] for e in evs if e["date"] != "2027-01-20")
        ck("AC-BE10-3 events(): E5 1.727.272,73 + E6 103.636,36 + 69.090,91 "
           "en 2027-01-10 (causacion) + E5 sin pct en 2027-01-20, en orden "
           "(fecha, concepto, id) y SIGMA compra A = T x Total = "
           "1.900.000,00 EXACTO",
           len(got) == 4 and all(
               got[i][0] == expected[i][0]
               and got[i][1] == expected[i][1]
               and approx(got[i][2], expected[i][2])
               for i in range(4))
           and approx(sigma_a, 1_900_000.0, 0.005), f"got={got}")
        evs_b = [e for e in evs if e["date"] == "2027-01-20"]
        ck("AC-BE10-3/D-S10-8 sin %int (Linea B): UN solo evento — E5 "
           "1.900.000,00 en la ancla — y CERO nacionalization_vat de B",
           len(evs_b) == 1 and evs_b[0]["concept"] == "import_vat"
           and approx(evs_b[0]["amount"], E5_NO_PCT), str(evs_b))

        # ── AC-BE10-7 unit: E4/E3 exactos y False mudo ──
        evf = eng.events(state.b_flags, FLAGS_YEAR)
        e4 = [e for e in evf
              if e["id_budget_line"] == state.flags_ids["vr"]]
        e3 = [e for e in evf
              if e["id_budget_line"] == state.flags_ids["vs"]]
        ef = [e for e in evf
              if e["id_budget_line"] == state.flags_ids["false"]]
        ck("AC-BE10-7 unit: E4 7.600.000 anclado al budget_date (R-S10-4,"
           " concept variable_expenses), E3 190.000 en 2044-06-05, y la "
           "linea has_iva=False NO emite evento (siquiera 0)",
           len(e4) == 1 and approx(e4[0]["amount"], 7_600_000.0)
           and e4[0]["date"] == "2044-05-10"
           and e4[0]["concept"] == "variable_expenses"
           and e4[0]["side"] == "deductible"
           and len(e3) == 1 and approx(e3[0]["amount"], 190_000.0)
           and e3[0]["date"] == "2044-06-05"
           and ef == [], f"e4={e4} e3={e3} false={ef}")

        # ── Paridad unit-vs-HTTP del contrato §4.6 ──
        unit = eng.settlement(state.b_rec, YEAR)
        http = settle(state.b_rec)
        ck("Paridad HTTP-vs-unit §4.6: settlement in-process == JSON de "
           "la API dict-a-dict (mismo codigo, cero deriva; clave LITERAL "
           "'deductable' presente)",
           unit == http and "deductable" in unit["totals"],
           f"unit={unit is not None} http={http is not None}")
        ck("NFR-BE10-4 determinismo: dos lecturas seguidas son "
           "identicas",
           eng.settlement(state.b_pur, YEAR)
           == eng.settlement(state.b_pur, YEAR))

        # ── NFR-BE10-1/2: pureza y economia MEDIDAS por eventos SQL ──
        counts = {"select": 0, "dml": 0}

        def _count(conn, cursor, statement, parameters, context,
                   executemany):
            s = statement.lstrip().upper()
            if s.startswith("SELECT"):
                counts["select"] += 1
            elif s.startswith(("INSERT", "UPDATE", "DELETE")):
                counts["dml"] += 1

        from sqlalchemy import event
        event.listen(engine, "before_cursor_execute", _count)
        try:
            counts["select"] = counts["dml"] = 0
            eng.settlement(state.b_pur, YEAR)     # compras con Linea
            n_full, dml_full = counts["select"], counts["dml"]
            counts["select"] = counts["dml"] = 0
            eng.settlement(state.b_nocal, NOCAL_YEAR)  # sin compras
            n_pure = counts["select"]
            counts["select"] = counts["dml"] = 0
            eng.events(state.b_flags, FLAGS_YEAR)
            n_events = counts["select"]
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        ck("NFR-BE10-1 (medido): settlement() NO emite NINGUN DML — cero "
           "materializacion de cuotas, eventos ni liquidaciones",
           dml_full == 0, f"dml={dml_full}")
        ck("NFR-BE10-2 (medido): Q1-Q7 constantes — 6 SELECTs con rate "
           "resuelto (Q5+Q6 presentes) y 4 sin compras con Linea "
           "(batches omitidos), siempre <= 8 e independiente de las "
           "lineas",
           n_full == 6 and n_pure == 4 and n_events == 4,
           f"full={n_full} pure={n_pure} events={n_events}")

        # ── §5.6 tabla de valores del mapeador ETL (in-process) ──
        import numpy as np
        import pandas as pd
        from app.utils.templates.budgetTemplates import BudgetTemplates
        m = BudgetTemplates._map_iva_flag
        trues = [m(v) for v in ("Si", "sí", "SÍ", "yes", "Y", "x", "X", 1,
                                1.0, "1", "1.0", "true", "Verdadero", True,
                                np.bool_(True))]
        falses = [m(v) for v in ("No", "not", "N", "false", "0", 0, 0.0,
                                 "falso", "FALSE", False, np.bool_(False))]
        nones = [m(v) for v in (None, float("nan"), pd.NA, pd.NaT, "",
                                "  ", "quiza", 7, "si pero", np.nan)]
        ck("§5.6 unit: si/sí/yes/y/x/1/true/verdadero (+numericos) => "
           "True; no/not/n/false/0/falso => False; NaN/vacio/garbage => "
           "None (≡ True por D-S10-3, jamas False implicito)",
           all(t is True for t in trues) and all(f is False
                                                 for f in falses)
           and all(n is None for n in nones),
           f"trues={trues} falses={falses} nones={nones}")

        # ── NFR-BE10-1 estatico: el modulo no tiene superficie de
        #    escritura (grep de db.add/commit/flush/delete) ──
        import inspect
        src = inspect.getsource(BudgetIvaEngine)
        ck("NFR-BE10-1 (estatico): el modulo del engine no contiene "
           "db.add/db.commit/db.flush/db.delete — capa 100% lectura",
           not any(tok in src for tok in ("db.add(", "db.commit(",
                                          "db.flush(", "db.delete(")),
           "grep-estatico")
    finally:
        db.close()
    return True


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Budget IVA Settlement Smoke (BE-S10-IVA)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Banco: Lineas/CECOS desechables + escenarios 'IVA *' en "
          f"{YEAR}/{NOCAL_YEAR}/{CAT_YEAR}/{FLAGS_YEAR}/{LM_YEAR}/"
          f"{ETL_YEAR1}/{ETL_YEAR2} (set cerrado barreable)")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    if not t02_setup_fixtures():
        print("ABORT: catalogos/calendarios de fixture no pudieron "
              "crearse")
        postclean()
        return 1
    if not t03_seed_scenarios():
        print("ABORT: los escenarios centinela no pudieron crearse")
        postclean()
        return 1
    print()

    tests = [
        t04_ac_be10_3_purchase_events,
        t05_ac_be10_4_recurrence,
        t06_ac_be10_5_catalog,
        t07_ac_be10_6_no_calendar,
        t08_ac_be10_7_flags_and_bases,
        t09_ac_be10_1_etl,
        t10_ac_be10_2_line_manager,
        t11_unit_be10,
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


# Punto de entrada coleccionable por pytest (los smokes del repo son
# scripts standalone; este envoltorio permite
# `python -m pytest test/test_budget_iva_smoke.py -x -q`).
def test_budget_iva_smoke_e2e():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
