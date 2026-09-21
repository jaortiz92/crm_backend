"""
Budget INTERNMENT Split Smoke Tests (BE-S9-INTERNMENT-SPLIT)

Spec: crm_backend/spec/backend.02_19_Spec_Backend_budgets_internment_split.md
§9. Patron de test_budget_purchases_smoke.py: corre contra el backend dev
real (:8003), JWT de .env_test, SQL de apoyo por psycopg2 (fallback docker
exec psql, con NULL-SENTINEL -P para distinguir NULL de '' real) y una
seccion UNIT in-process (importa app.crud.budget.planning contra la misma
BD dev) para los edges de derivacion §4 y la economia de queries medida.

Cubre:
     AC-BE9-1  Catalogo rate: POST {id_line, internment_pct .20} -> 201;
               duplicado sobre la MISMA Linea -> 400 "Line {id} already has
               an internment rate"; pct 1.5 -> 422; pct 0 -> 422; GET
               /by-line/{line} sin tasa -> 200 null (la ausencia NO es
               error); PUT con id_line inexistente -> 404 "Line {id} not
               found"; PUT a Linea con tasa ajena (re-parent) -> 400
               literal analogo; PUT re-save de la propia Linea -> 200
               idempotente; PUT inexistente -> 404 "LineInternmentRate {id}
               not found"; DELETE -> {"deleted_id": n} y el by-line vuelve
               a null; DELETE repetido -> 404.
     AC-BE9-2  Catalogo term (espejo AC-S5-BE): 2 POST -> 201; GET /by-line
               en orden D-7 (payment_days ASC, id ASC) SIN importar el
               orden de insercion; pct 1.5 / pct 0 / days no-int -> 422;
               POST con id_line inexistente -> 404 "Line {id} not found";
               PUT inexistente -> 404 "LineInternmentTerm {id} not found";
               PUT full-replacement -> 200 con valores nuevos; GET /by-line
               de Linea desconocida -> []; GET / contiene las filas; DELETE
               responde el id y /by-line queda [].
     AC-BE9-3  Desglose end-to-end (EJEMPLO VOBATIM DE LA SPEC §9): compra
               120 000 000 anclada 15/12/2026 en un CECO de una Linea con
               rate 0.20, terminos proveedor +30@.5/+60@.5 y terminos
               internacion +15@.6/+45@.4; escenario objetivo 2027 con flag
               ON -> GET /{id}/carryover responde EXACTAMENTE 3 filas:
               purchase 2027-01-14 50 000 000 | internment 2027-01-29
               8 000 000 | purchase 2027-02-13 50 000 000 (la cuota int
               12 000 000 del 30/12/2026 queda EXCLUIDA por BR-CO-09);
               descripciones literales "Pago a proveedor (arrastre)" /
               "Pago de internacion (arrastre)"; cero filas cogs de esa
               Linea (switch D-4' intacto, espejo AC-BE8-5: el ingreso
               comprador sembrado en la fuente NO deriva costo).
     AC-BE9-4  Regresion (NFR-BE9-3, lado UNIT): Linea SIN rate -> la
               cuota purchase es BIT-FOR-BIT el monto pre-cambio
               (total × payment_pct con total/1.0 exacto) y CERO filas
               internment; el purchases smoke existente
               (test_budget_purchases_smoke.py) NO se toca y sigue siendo
               la prueba de payload identico (spec §9: "corrida del
               purchases smoke existente sin modificar").
     AC-BE9-5  Edges nivel crud (unit): pct > 0 y CERO int-terminos -> UNA
               fila internment al 100 % del costo_int en la fecha de
               importacion (BR-INT-04); pct = 0 -> cero filas (BR-INT-05);
               terminos int con payment_days que cae en el anio objetivo
               -> incluida (BR-CO-09 aplicado por cuota a AMBOS streams);
               compras en CECOs sin Linea -> set de Lineas vacio => los 2
               queries batch se OMITEN (1 solo SELECT, cota alta de
               NFR-BE9-2 preservada).
     AC-BE9-6  Rank de empate (BR-CO-10 extendido): cuota purchase e
               internment con FECHA EFECTIVA IDENTICA -> la internment
               ordena DESPUES (rank 3 sobre 2) en build_carryover_payload_
               lines; adentro de get_carryover_purchase_lines el stream
               proveedor se genera ANTES que el de internacion (NFR-BE9-4).
     AC-BE9-7  Fila intacta: GET /{id}/detail sin campos nuevos (set de
               claves de una compra == set de un ingreso, cero columnas
               *internment* en budget_lines via information_schema) y
               guards del line manager byte-identicos (POST purchase con
               variable_rate -> 400 {reason: PURCHASE_SHAPE_REASON}; PUT
               payment_date -> 400 {reason: PURCHASE_PAYMENT_REASON}).
     NFR-BE9-2  (medido in-process con eventos SQLAlchemy): +2 queries
               batch maximos cuando las compras resuelven Linea (main +
               rates + int-terms = 3) y 1 sola cuando no (batch omitido).
     NFR-BE9-5  Evidencia de create_all: las 2 tablas nuevas existen en el
               schema con COUNT=0 tras el arranque (el dev ya corrio el
               reload; la verificacion de residuo al final vuelve a 0).

Banco de pruebas: 5 Lineas desechables ('SMOKE BE9 A'..'E', ids explicitos
max+1 — las secuencias de la dev estan desincronizadas por el seed
historico, nota replicada del purchases smoke), 5 CECOS desechables con
codes fijos '998710'..'998714' (998714 SIN id_line = centinela lineless) y
escenarios SEMBRADOS CON NOMBRE 'INTERN *'. A DIFERENCIA del purchases
smoke, el ejemplo VOBATIM de AC-BE9-3 usa los anios REALES 2026 (fuente) y
2027 (objetivo) que la spec §9 fija — por eso la fuente lleva status
'active' (el pick BR-CO-02 elige ACTIVE > ... y, dentro de active,
updated_at DESC: la fila sembrada por el smoke es la mas nueva => gana
deterministicamente contra el 'Prueba5-2026' real mientras dure la
ventana), el SWEEP BORRA SOLO POR NOMBRE/CODIGO/MARCA (jamas por anio:
los 2026/2027 reales del proyecto NO se tocan) y la ventana deja una
activa 2026 transitoria visible en listados ajenos. Las demas fuentes
(SRC_B/C/D/X) son draft: nunca ganan el pick y solo las consume la
seccion unit. Los terminos/tasas de fixture se crean VIA API (validan
tambien el camino feliz POST); la Linea E queda libre para los CRUD
tests de catalogo y se limpia con DELETE dentro de su propio test.
Pre-clean y post-clean GARANTIZADOS (try/finally) con verificacion de 0
restos en las 6 tablas tocadas.

Uso:
    1. docker compose -f docker-compose-dev.yaml up   (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD
    3. python test/test_budget_internment_smoke.py     (desde crm_backend/)
       — la seccion unit exige el interprete con las deps del backend
       (venv_backend/Scripts/python.exe o equivalente: sqlalchemy, fastapi,
       pydantic-settings, psycopg2), porque importa app.crud en el proceso
       con env vars sintetizadas hacia la BD dev de .env_test
"""

import sys
import traceback
from datetime import date, timedelta
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

MARK = "INTERN "         # prefijo de aislamiento de nombres de budgets
LINE_MARK = "SMOKE BE9"  # prefijo de aislamiento de line_name
CC_CODES = ("998710", "998711", "998712", "998713", "998714")
SRC_YEAR = 2026          # anio de la fuente (EJEMPLO VOBATIM spec §9)
TGT_YEAR = 2027          # anio objetivo (flag ON)
TOL = 0.01               # tolerancia COP para montos derivados (float /1.2)

# Literales exactos del contrato (spec backend.02_19 §5.3 — quoted by the
# acceptance criteria, so they win over any helper formatting).
RATE_DUP_TPL = "Line {} already has an internment rate"
LINE_NF_TPL = "Line {} not found"
RATE_NF_TPL = "LineInternmentRate {} not found"
TERM_NF_TPL = "LineInternmentTerm {} not found"
PURCHASE_DESC = "Pago a proveedor (arrastre)"
INTERNMENT_DESC = "Pago de internación (arrastre)"
# Guards BR-PUR-02/04 del line manager (BE-S7/BE-S8, AC-BE9-7: intactos).
PURCHASE_SHAPE_REASON = (
    "purchase lines must be fixed with no variable rate"
)
PURCHASE_PAYMENT_REASON = (
    "payment dates of a purchase derive from the line's payable terms"
)

state = type("S", (), {})()
state.headers = {}
state.token = None
state.lines = {}            # letter -> id_line (A..E)
state.ccs = {}              # letter -> id_cost_center (A,B,C,D,X lineless)
state.src_main = None       # 2026 ACTIVE: compra 120M + ingreso comprador
state.tgt = None            # 2027 flag ON (AC-BE9-3/6/7/8 HTTP)
state.src_b = None          # 2026 draft: compra linea SIN rate (unit)
state.src_c = None          # 2026 draft: compra rate sin int-terminos (unit)
state.src_d = None          # 2026 draft: compra con empates de fecha (unit)
state.src_x = None          # 2026 draft: compra CECO sin linea (unit)
state.main_pur = None       # id_budget_line de la compra 120M (AC-BE9-7)
state.main_inc = None       # id_budget_line del ingreso comprador (biseccion)
state.total = 0
state.passed = 0
state.failed = 0
state.results = []


# ══════════════════════════════════════════════════════════════
# UTILIDADES (mismos patrones de test_budget_purchases_smoke.py)
# ══════════════════════════════════════════════════════════════

def api(method, endpoint, auth=True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = dict(state.headers) if auth else {}
    headers.update(kwargs.pop("headers", {}))
    try:
        return requests.request(method, url, headers=headers, timeout=120, **kwargs)
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


def insert_budget(name, year, status_kind):
    return int(sql_scalar(
        "INSERT INTO budgets (budget_name, budget_year, budget_period, status)"
        f" VALUES ('{name}', {year}, 'ANUAL', '{status_kind}') "
        "RETURNING id_budget"))


def insert_line(budget_id, cc, ltype, bdate, pdate, amount, desc,
                behavior="FIXED"):
    p = f"'{pdate}'" if pdate else "NULL"
    return int(sql_scalar(
        "INSERT INTO budget_lines (id_budget, id_cost_center, line_type, "
        "budget_date, payment_date, projected_amount, description, "
        "behavior_type) VALUES "
        f"({budget_id}, {cc}, '{ltype}', '{bdate}', {p}, {amount}, "
        f"'{desc}', '{behavior}') RETURNING id_budget_line"))


def detail_line(budget_id, line_id):
    r = api("GET", f"/budget/planning/{budget_id}/detail")
    if r is None or r.status_code != 200:
        return None
    return next((l for l in r.json()["budget_lines"]
                 if l["id_budget_line"] == line_id), None)


def carry_payload(budget_id):
    r = api("GET", f"/budget/planning/{budget_id}/carryover")
    return r.json() if r is not None and r.status_code == 200 else None


def payload_tuples(payload):
    """[(fecha_efectiva_iso, origin, id_cost_center, monto)] en el ORDEN
    EXACTO de la respuesta (verifica tambien el BR-CO-10 extendido)."""
    return [
        (l["payment_date"] or l["budget_date"], l["origin"],
         l["id_cost_center"], l["projected_amount"])
        for l in payload["lines"]
    ]


def close_tuples(actual, expected):
    if len(actual) != len(expected):
        return False
    for (d1, o1, c1, a1), (d2, o2, c2, a2) in zip(actual, expected):
        if (d1, o1, c1) != (d2, o2, c2) or abs(a1 - a2) > TOL:
            return False
    return True


def row_tuples(rows):
    """[(fecha_efectiva, origin, monto)] de dicts de derivacion in-process
    (get_carryover_purchase_lines) u objetos PlanningCarryoverLine (build)."""
    out = []
    for r in rows:
        if isinstance(r, dict):
            eff = r["payment_date"] or r["budget_date"]
            out.append((eff, r["origin"], r["projected_amount"]))
        else:
            eff = r.payment_date or r.budget_date
            out.append((eff, r.origin, r.projected_amount))
    return out


# ══════════════════════════════════════════════════════════════
# LIMPIEZA (pre/post garantizados) — SOLO por marca/nombre/codigo:
# los anios 2026/2027 son REALES y jamas se barren por anio.
# ══════════════════════════════════════════════════════════════

def sweep():
    # lineas + budgets 'INTERN *' (orden FK-safe)
    run_sql("DELETE FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_name LIKE '{MARK}%')")
    run_sql(f"DELETE FROM budgets WHERE budget_name LIKE '{MARK}%'")
    # catalogos de las Lineas desechables (pagos, internacion: tasas+terminos)
    run_sql("DELETE FROM line_payable_terms WHERE id_line IN "
            f"(SELECT id_line FROM lines WHERE line_name LIKE '{LINE_MARK}%')")
    run_sql("DELETE FROM line_internment_terms WHERE id_line IN "
            f"(SELECT id_line FROM lines WHERE line_name LIKE '{LINE_MARK}%')")
    run_sql("DELETE FROM line_internment_rates WHERE id_line IN "
            f"(SELECT id_line FROM lines WHERE line_name LIKE '{LINE_MARK}%')")
    # CECOS + Lineas desechables
    run_sql("DELETE FROM budget_lines WHERE id_cost_center IN "
            "(SELECT id_cost_center FROM cost_centers "
            f" WHERE cost_center_code IN {tuple(CC_CODES)})")
    run_sql("DELETE FROM cost_centers WHERE cost_center_code IN "
            f"{tuple(CC_CODES)}")
    run_sql(f"DELETE FROM lines WHERE line_name LIKE '{LINE_MARK}%'")


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
        rest_l = int(sql_scalar(
            "SELECT count(*) FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_name LIKE '{MARK}%')"))
        rest_cc = int(sql_scalar(
            "SELECT count(*) FROM cost_centers WHERE cost_center_code IN "
            f"{tuple(CC_CODES)}"))
        rest_ln = int(sql_scalar(
            f"SELECT count(*) FROM lines WHERE line_name LIKE '{LINE_MARK}%'"))
        rest_cat = int(sql_scalar(
            "SELECT (SELECT count(*) FROM line_internment_rates WHERE id_line"
            "        IN (SELECT id_line FROM lines WHERE line_name LIKE "
            f"                 '{LINE_MARK}%')) "
            "     + (SELECT count(*) FROM line_internment_terms WHERE id_line"
            "        IN (SELECT id_line FROM lines WHERE line_name LIKE "
            f"                 '{LINE_MARK}%')) "
            "     + (SELECT count(*) FROM line_payable_terms WHERE id_line"
            "        IN (SELECT id_line FROM lines WHERE line_name LIKE "
            f"                 '{LINE_MARK}%'))"))
        return ck("Limpieza garantizada: 0 restos (budgets/lineas/CECO/"
                  "Lineas/catalogos)",
                  rest_b == 0 and rest_l == 0 and rest_cc == 0
                  and rest_ln == 0 and rest_cat == 0,
                  f"budgets={rest_b} lineas={rest_l} ceco={rest_cc} "
                  f"lines={rest_ln} catalogs={rest_cat}")
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
        f"'{code}', '{name}', true, 'BE-S9 smoke: {name}', {lin}) "
        "RETURNING id_cost_center"))


def _post(endpoint, body, name):
    """POST + asercion 201 de setup (los verbos de catalogo se prueban a
    fondo en t04/t05 sobre la Linea E; aqui solo se construye el fixture)."""
    r = api("POST", endpoint, json=body)
    if r is None or r.status_code != 201:
        ck(f"Setup {name} -> 201", False,
           (r.text[:120] if r is not None else "error"))
        return None
    return r.json()


def t02_setup_fixtures():
    """Lineas/CECOS desechables + catalogos del fixture VIA API (camino
    feliz POST de los endpoints nuevos incluidos). Linea E libre para los
    CRUD tests de t04/t05. NB ids explicitos max+1: las secuencias de la
    dev estan desincronizadas (seed historico; nota del purchases smoke).
    NFR-BE9-5: primera señal = las 2 tablas nuevas existen con COUNT=0."""
    tab_r = int(sql_scalar(
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name='line_internment_rates'"))
    tab_t = int(sql_scalar(
        "SELECT count(*) FROM information_schema.tables WHERE "
        "table_name='line_internment_terms'"))
    n_r = sql_scalar("SELECT count(*) FROM line_internment_rates")
    n_t = sql_scalar("SELECT count(*) FROM line_internment_terms")
    ck("NFR-BE9-5: create_all creo las 2 tablas nuevas (0 DDL manual), "
       "con 0 filas al arrancar el smoke",
       tab_r == 1 and tab_t == 1 and int(n_r) == 0 and int(n_t) == 0,
       f"tablas={tab_r}/{tab_t} rows={n_r}/{n_t}")

    for letter in "ABCDE":
        state.lines[letter] = _insert_line_id(letter)
    for i, letter in enumerate(("A", "B", "C", "D", "X")):
        id_line = None if letter == "X" else state.lines[letter]
        state.ccs[letter] = _insert_cc(CC_CODES[i], f"{LINE_MARK} cc{letter}",
                                       id_line)
    ck("Setup: 5 Lineas + 5 CECOS desechables (X sin id_line)",
       len(state.lines) == 5 and len(state.ccs) == 5)

    ok = True
    # tasas de internacion: A .20 (ejemplo verbatim), C .25, D .50; B SIN
    for spec in (("A", 0.20), ("C", 0.25), ("D", 0.50)):
        ok &= _post("/budget/line-internment-rate/",
                    {"id_line": state.lines[spec[0]],
                     "internment_pct": spec[1]},
                    f"rate {spec[0]}={spec[1]}") is not None
    # terminos proveedor (line_payable_terms — mecánica intacta, nueva base)
    for spec in ((("A", 30, 0.5)), (("A", 60, 0.5)), (("B", 20, 1.0)),
                 (("C", 20, 1.0)), (("D", 20, 0.5)), (("D", 50, 0.5))):
        ok &= _post("/budget/line-payable-term/",
                    {"id_line": state.lines[spec[0]],
                     "payment_days": spec[1], "payment_pct": spec[2]},
                    f"payable {spec}") is not None
    # terminos internacion: A +15@.6/+45@.4 (verbatim), D +20@.5/+50@.5
    # (empates); C SIN terminos => BR-INT-04
    for spec in (("A", 15, 0.6), ("A", 45, 0.4), ("D", 20, 0.5),
                 ("D", 50, 0.5)):
        ok &= _post("/budget/line-internment-term/",
                    {"id_line": state.lines[spec[0]],
                     "payment_days": spec[1], "payment_pct": spec[2]},
                    f"int-term {spec}") is not None
    return ck("Setup: catalogos de fixture sembrados via API (A/C/D rates, "
              "payables A-D, intern-terms A y D)", bool(ok))


def t03_seed_scenarios():
    """Fuente 2026 'INTERN src' ACTIVE (el pick BR-CO-02 la elige por
    updated_at DESC mas nuevo; ver header — unico momento en que el smoke
    toca un anio real) con la compra 120M anclada 15/12/2026 + ingreso del
    MISMO CECO (switch D-4' => cero cogs); target 2027 'INTERN tgt' con
    flag ON via API; y las 4 fuentes draft de la seccion unit (B sin rate,
    C rate sin terminos int, D empates, X CECO sin linea)."""
    state.src_main = insert_budget(MARK + "src 2026", SRC_YEAR, "active")
    state.tgt = insert_budget(MARK + "tgt 2027", TGT_YEAR, "draft")
    state.main_pur = insert_line(state.src_main, state.ccs["A"], "PURCHASE",
                                 "2026-12-15", None, 120_000_000,
                                 "BE9 compra verbatim 120M")
    state.main_inc = insert_line(state.src_main, state.ccs["A"], "INCOME",
                                 "2026-06-15", "2026-06-20", 7_000_000,
                                 "BE9 ingreso comprador (D-4) 2026")
    state.src_b = insert_budget(MARK + "b 2026", SRC_YEAR, "draft")
    insert_line(state.src_b, state.ccs["B"], "PURCHASE", "2026-12-20", None,
                100_000_000, "BE9 compra sin rate 100M")
    state.src_c = insert_budget(MARK + "c 2026", SRC_YEAR, "draft")
    insert_line(state.src_c, state.ccs["C"], "PURCHASE", "2026-12-20", None,
                60_000_000, "BE9 compra rate sin int-terms 60M")
    state.src_d = insert_budget(MARK + "d 2026", SRC_YEAR, "draft")
    insert_line(state.src_d, state.ccs["D"], "PURCHASE", "2026-12-31", None,
                24_000_000, "BE9 compra empates 24M")
    state.src_x = insert_budget(MARK + "x 2026", SRC_YEAR, "draft")
    insert_line(state.src_x, state.ccs["X"], "PURCHASE", "2026-12-10", None,
                5_000_000, "BE9 compra CECO sin linea 5M")
    rf = api("PUT", f"/budget/planning/{state.tgt}/carryover",
             json={"include_carryover": True})
    ok = rf is not None and rf.status_code == 200
    return ck("Fixture: fuente 2026 ACTIVE (compra 120M 15/12 + ingreso "
              "comprador) + target 2027 flag ON + 4 fuentes draft unit",
              ok, (rf.text[:100] if rf is not None and not ok else ""))


def t04_ac_be9_1_rate_catalog():
    """AC-BE9-1: los 9 literales/verbos del catalogo de tasas sobre la
    Linea E (libre de fixture)."""
    line = state.lines["E"]
    r1 = api("POST", "/budget/line-internment-rate/",
             json={"id_line": line, "internment_pct": 0.20})
    ok1 = r1 is not None and r1.status_code == 201 and r1.json().get(
        "id_line") == line and r1.json().get("internment_pct") == 0.20
    ck("AC-BE9-1 POST {id_line, .20} -> 201 eco", ok1,
       (r1.text[:120] if r1 is not None else "error"))
    if not ok1:
        return False
    rid = r1.json()["id_line_internment_rate"]

    r2 = api("POST", "/budget/line-internment-rate/",
             json={"id_line": line, "internment_pct": 0.30})
    ck("AC-BE9-1 duplicado -> 400 \"Line {id} already has an internment "
       "rate\" (CRUD None -> API literal)",
       r2 is not None and r2.status_code == 400
       and r2.json().get("detail") == RATE_DUP_TPL.format(line),
       (r2.text[:130] if r2 is not None else "error"))

    r3 = api("POST", "/budget/line-internment-rate/",
             json={"id_line": line, "internment_pct": 1.5})
    r4 = api("POST", "/budget/line-internment-rate/",
             json={"id_line": line, "internment_pct": 0})
    ck("AC-BE9-1 pct 1.5 -> 422 y pct 0 -> 422 (Field gt=0, le=1)",
       r3 is not None and r3.status_code == 422
       and r4 is not None and r4.status_code == 422,
       f"{r3.status_code if r3 is not None else 'err'}/{r4.status_code if r4 is not None else 'err'}")

    r5 = api("GET", f"/budget/line-internment-rate/by-line/{line}")
    r6 = api("GET", "/budget/line-internment-rate/by-line/99999999")
    ck("AC-BE9-1 GET /by-line: tasa -> objeto; sin tasa (o Linea ignota) "
       "-> 200 null (la ausencia NO es error)",
       r5 is not None and r5.status_code == 200
       and r5.json() is not None
       and r5.json()["id_line_internment_rate"] == rid
       and r6 is not None and r6.status_code == 200 and r6.json() is None,
       f"{(r5.status_code, r5.json() is not None) if r5 is not None else None}"
       f"/{(r6.status_code, r6.json()) if r6 is not None else None}")

    r7 = api("GET", "/budget/line-internment-rate/")
    ck("AC-BE9-1 GET / catalogo incluye la tasa (orden id_line)",
       r7 is not None and r7.status_code == 200
       and any(x["id_line_internment_rate"] == rid for x in r7.json()))

    r8 = api("PUT", f"/budget/line-internment-rate/{rid}",
             json={"id_line": 999999, "internment_pct": 0.25})
    ck("AC-BE9-1 PUT con id_line inexistente -> 404 \"Line 999999 not "
       "found\" (guard FK, mismo literal que POST)",
       r8 is not None and r8.status_code == 404
       and r8.json().get("detail") == LINE_NF_TPL.format(999999),
       (r8.text[:120] if r8 is not None else "error"))

    r9 = api("PUT", f"/budget/line-internment-rate/{rid}",
             json={"id_line": state.lines["A"], "internment_pct": 0.25})
    ck("AC-BE9-1 PUT re-parent a Linea con tasa propia -> 400 \"Line {id} "
       "already has an internment rate\" (literal análogo)",
       r9 is not None and r9.status_code == 400
       and r9.json().get("detail") == RATE_DUP_TPL.format(state.lines["A"]),
       (r9.text[:130] if r9 is not None else "error"))

    r10 = api("PUT", f"/budget/line-internment-rate/{rid}",
              json={"id_line": line, "internment_pct": 0.30})
    ck("AC-BE9-1 PUT re-save de la PROPIA Linea -> 200 idempotente (no "
       "colisiona consigo misma), pct reemplazado",
       r10 is not None and r10.status_code == 200
       and r10.json().get("internment_pct") == 0.30
       and r10.json().get("id_line") == line,
       (r10.text[:120] if r10 is not None else "error"))

    r11 = api("PUT", "/budget/line-internment-rate/99999999",
              json={"id_line": line, "internment_pct": 0.25})
    ck("AC-BE9-1 PUT inexistente -> 404 \"LineInternmentRate {id} not "
       "found\"",
       r11 is not None and r11.status_code == 404
       and r11.json().get("detail") == RATE_NF_TPL.format(99999999),
       (r11.text[:120] if r11 is not None else "error"))

    r12 = api("DELETE", f"/budget/line-internment-rate/{rid}")
    r13 = api("GET", f"/budget/line-internment-rate/by-line/{line}")
    ck("AC-BE9-1 DELETE -> {\"deleted_id\": n} y el /by-line vuelve a "
       "null (ausencia = pct 0)",
       r12 is not None and r12.status_code == 200
       and r12.json() == {"deleted_id": rid}
       and r13 is not None and r13.status_code == 200
       and r13.json() is None,
       (r12.text[:80] if r12 is not None else "error"))

    r14 = api("DELETE", f"/budget/line-internment-rate/{rid}")
    return ck("AC-BE9-1 DELETE repetido -> 404 mismo literal",
              r14 is not None and r14.status_code == 404
              and r14.json().get("detail") == RATE_NF_TPL.format(rid),
              (r14.text[:120] if r14 is not None else "error"))


def t05_ac_be9_2_term_catalog():
    """AC-BE9-2 (espejo AC-S5-BE sobre el catalogo de terminos de
    internacion): orden D-7, [] si ausencia, 422 pct ∉ (0,1], FK 404,
    DELETE responde id."""
    line = state.lines["E"]
    ra = api("POST", "/budget/line-internment-term/",
             json={"id_line": line, "payment_pct": 0.40, "payment_days": 45})
    rb = api("POST", "/budget/line-internment-term/",
             json={"id_line": line, "payment_pct": 0.60, "payment_days": 15})
    ok_post = (ra is not None and ra.status_code == 201
               and rb is not None and rb.status_code == 201)
    ck("AC-BE9-2 POST x2 -> 201", ok_post,
       (rb.text[:110] if rb is not None else "error"))
    if not ok_post:
        return False
    id_a, id_b = ra.json()["id_line_internment_term"], \
        rb.json()["id_line_internment_term"]

    r1 = api("GET", f"/budget/line-internment-term/by-line/{line}")
    days = [t["payment_days"] for t in r1.json()]
    ck("AC-BE9-2 GET /by-line orden D-7 (payment_days ASC, id ASC) pese a "
       "insertar 45 antes que 15", days == [15, 45], f"days={days}")

    r2 = api("POST", "/budget/line-internment-term/",
             json={"id_line": line, "payment_pct": 1.5, "payment_days": 30})
    r3 = api("POST", "/budget/line-internment-term/",
             json={"id_line": line, "payment_pct": 0, "payment_days": 30})
    r4 = api("POST", "/budget/line-internment-term/",
             json={"id_line": line, "payment_pct": 0.5, "payment_days": 1.5})
    ck("AC-BE9-2 pct 1.5 / pct 0 / days 1.5 -> 422 (Field validators)",
       r2 is not None and r2.status_code == 422
       and r3 is not None and r3.status_code == 422
       and r4 is not None and r4.status_code == 422,
       f"{r2.status_code if r2 is not None else 'e'}/{r3.status_code if r3 is not None else 'e'}"
       f"/{r4.status_code if r4 is not None else 'e'}")

    r5 = api("POST", "/budget/line-internment-term/",
             json={"id_line": 999999, "payment_pct": 0.5, "payment_days": 1})
    ck("AC-BE9-2 POST id_line inexistente -> 404 \"Line 999999 not found\"",
       r5 is not None and r5.status_code == 404
       and r5.json().get("detail") == LINE_NF_TPL.format(999999),
       (r5.text[:110] if r5 is not None else "error"))

    r6 = api("PUT", f"/budget/line-internment-term/{id_a}",
             json={"id_line": line, "payment_pct": 0.25, "payment_days": 90})
    ck("AC-BE9-2 PUT full-replacement -> 200 con los valores nuevos",
       r6 is not None and r6.status_code == 200
       and r6.json().get("payment_days") == 90
       and r6.json().get("payment_pct") == 0.25,
       (r6.text[:110] if r6 is not None else "error"))

    r7 = api("PUT", "/budget/line-internment-term/99999999",
             json={"id_line": line, "payment_pct": 0.5, "payment_days": 7})
    ck("AC-BE9-2 PUT inexistente -> 404 \"LineInternmentTerm {id} not "
       "found\"",
       r7 is not None and r7.status_code == 404
       and r7.json().get("detail") == TERM_NF_TPL.format(99999999),
       (r7.text[:110] if r7 is not None else "error"))

    r8 = api("GET", "/budget/line-internment-term/by-line/99999999")
    ck("AC-BE9-2 GET /by-line de Linea desconocida -> [] (la ausencia NO "
       "es error; derivacion degrada a BR-INT-04)",
       r8 is not None and r8.status_code == 200 and r8.json() == [])

    r9 = api("GET", "/budget/line-internment-term/")
    ck("AC-BE9-2 GET / catalogo contiene las 2 filas de la Linea E",
       r9 is not None and r9.status_code == 200
       and {id_a, id_b} <= {t["id_line_internment_term"]
                            for t in r9.json()})

    rd1 = api("DELETE", f"/budget/line-internment-term/{id_a}")
    rd2 = api("DELETE", f"/budget/line-internment-term/{id_b}")
    r10 = api("GET", f"/budget/line-internment-term/by-line/{line}")
    ck("AC-BE9-2 DELETE responde {\"deleted_id\": id} (x2) y /by-line "
       "queda []",
       rd1 is not None and rd1.json() == {"deleted_id": id_a}
       and rd2 is not None and rd2.json() == {"deleted_id": id_b}
       and r10 is not None and r10.json() == [])
    return True


def t06_ac_be9_3_end_to_end():
    """AC-BE9-3 verbatim (spec §9): compra 120M @ 15/12/2026, rate .20,
    proveedor +30@.5/+60@.5, internacion +15@.6/+45@.4 => target 2027
    EXACTAMENTE 3 filas (prov 50M @ 2027-01-14, int 8M @ 2027-01-29, prov
    50M @ 2027-02-13; los 12M @ 2026-12-30 EXCLUIDOS por BR-CO-09)."""
    payload = carry_payload(state.tgt)
    if payload is None or not payload.get("enabled"):
        return ck("AC-BE9-3 GET carryover 2027 habilitado", False,
                  str(payload)[:120])
    ck("AC-BE9-3 source = la fuente 2026 sembrada (BR-CO-02 gana por "
       "updated_at DESC dentro de active)",
       (payload.get("source") or {}).get("id_budget") == state.src_main,
       f"source={payload.get('source')}")

    # Espejo INDEPENDIENTE de §4 (no reusa el codigo del backend):
    # costo_prov = 120.000.000/1,2 = 50M por cuota .5; costo_int = 20M
    # => 12M @ 30/12/2026 (fuera de N) y 8M @ 29/01/2027.
    expected = [
        ("2027-01-14", "purchase", state.ccs["A"], 50_000_000.0),
        ("2027-01-29", "internment", state.ccs["A"], 8_000_000.0),
        ("2027-02-13", "purchase", state.ccs["A"], 50_000_000.0),
    ]
    got = payload_tuples(payload)
    ck("AC-BE9-3 payload EXACTO: 3 filas fecha/origin/CECO/monto en orden "
       "BR-CO-10 (14/01 prov 50M · 29/01 int 8M · 13/02 prov 50M)",
       close_tuples(got, expected), f"got={got} exp={expected}")
    ck("AC-BE9-3/BR-CO-09: la cuota internacion 12 000 000 del 30/12/2026 "
       "queda EXCLUIDA del arrastre 2027",
       all(l["payment_date"] != "2026-12-30" and l["budget_date"] !=
           "2026-12-30" for l in payload["lines"]))

    by_origin = {l["origin"]: l for l in payload["lines"]}
    ck("AC-BE9-3 descripciones literales por stream (\"Pago a proveedor "
       "(arrastre)\" / \"Pago de internación (arrastre)\")",
       all(l["description"] == PURCHASE_DESC
           for l in payload["lines"] if l["origin"] == "purchase")
       and all(l["description"] == INTERNMENT_DESC
               for l in payload["lines"] if l["origin"] == "internment"))
    ck("AC-BE9-3 forma de las filas (ambos streams): line_type 'expense', "
       "id_budget_line null, budget_date = ancla de importacion 15/12/2026 "
       "compartida (A-3)",
       all(l["line_type"] == "expense" and l["id_budget_line"] is None
           and l["budget_date"] == "2026-12-15"
           for l in payload["lines"])
       and {"purchase", "internment"} <= set(by_origin))
    ck("AC-BE9-3 switch D-4' intacto (espejo AC-BE8-5): el ingreso del "
       "CECO comprador NO deriva fila 'cogs' — cero filas cogs de la "
       "Linea (y de ninguna)",
       not any(l["origin"] == "cogs" for l in payload["lines"]))
    return True


def t07_ac_be9_7_row_intact():
    """AC-BE9-7: la FILA no cambio de forma — detail sin campos nuevos
    (set de claves de la compra == set de un ingreso; cero columnas
    *internment* en budget_lines) y guards BR-PUR-02/04 byte-identicos."""
    pur = detail_line(state.src_main, state.main_pur)
    inc = detail_line(state.src_main, state.main_inc)
    if pur is None or inc is None:
        return ck("AC-BE9-7 detail legible (compra + ingreso)", False)
    ck("AC-BE9-7 GET /detail: la compra conserva payment_date NULL y su "
       "forma exacta (set de claves identico al de un ingreso — cero "
       "campos nuevos de internacion)",
       pur["line_type"] == "purchase" and pur["payment_date"] is None
       and set(pur.keys()) == set(inc.keys())
       and not any("internment" in k for k in pur))
    cols = int(sql_scalar(
        "SELECT count(*) FROM information_schema.columns WHERE "
        "table_name='budget_lines' AND column_name LIKE '%internment%'"))
    ck("NFR-BE9-5/AC-BE9-7: budget_lines NO recibio columnas nuevas "
       "(las tasas/terminos viven en las 2 tablas satélite — cero ALTER)",
       cols == 0, f"cols={cols}")
    r1 = api("POST", f"/budget/planning/{state.src_main}/line", json={
        "id_cost_center": state.ccs["A"], "line_type": "purchase",
        "budget_date": "2026-05-05", "projected_amount": 1.0,
        "behavior_type": "variable_sales", "variable_rate": 0.5})
    ok1 = (r1 is not None and r1.status_code == 400
           and (r1.json().get("detail") or {}).get("reason")
           == PURCHASE_SHAPE_REASON)
    r2 = api("PUT", f"/budget/planning/line/{state.main_pur}",
             json={"payment_date": "2027-01-01"})
    ok2 = (r2 is not None and r2.status_code == 400
           and (r2.json().get("detail") or {}).get("reason")
           == PURCHASE_PAYMENT_REASON)
    return ck("AC-BE9-7 guards del line manager intactos: POST "
              "purchase+variable_rate -> 400 {reason: forma BR-PUR-02}; "
              "PUT payment_date -> 400 {reason: BR-PUR-04}",
              ok1 and ok2,
              f"post={r1.status_code if r1 is not None else 'err'} "
              f"put={r2.status_code if r2 is not None else 'err'}")


def _unit_planning():
    """Importa el MISMO codigo del backend (modulo montado en el contenedor
    dev :8003) dentro de este proceso para los checks unit §4/BR-INT-04/05
    y la economia de queries medida, con sesion SQLAlchemy propia contra la
    BD dev de .env_test. Los env vars de app/settings.py se sintetizan
    ANTES del import (sin .env en el host); `import app.api` va primero
    porque es el orden que rompe el ciclo core.auth <-> app.api.utils en el
    arranque real (importar app.crud directamente lo dispararia)."""
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
    from app.crud.budget import planning
    from app.db import SessionLocal, engine
    return planning, SessionLocal, engine


def t08_unit_be9():
    """Checks in-process sobre la misma BD con el fixture vivo de t03:
    AC-BE9-4/NFR-BE9-3 (regresion bit-for-bit sin rate), AC-BE9-5 (edges
    BR-INT-04/05 + batch-skip lineless), AC-BE9-6 (orden prov->int y rank
    de empate), NFR-BE9-2 (queries medidos) y paridad unit-vs-HTTP."""
    try:
        planning, SessionLocal, engine = _unit_planning()
    except Exception as e:
        return ck("Unit BE9: import app.crud.budget.planning in-process",
                  False, f"{type(e).__name__}: {str(e)[:130]}")
    ck("Unit BE9: import app.crud.budget.planning in-process (mismo "
       "modulo que sirve :8003 via volumen montado)", True)
    db = SessionLocal()
    try:
        # ── AC-BE9-4 / NFR-BE9-3: Linea SIN rate — montos BIT-FOR-BIT
        # identicos a la derivacion pre-cambio (total/1.0 == total exacto).
        rows_b = planning.get_carryover_purchase_lines(db, state.src_b, 2027)
        exp_amount_b = 100_000_000.0 * 1.0        # formula vieja exacta
        ok_b = (len(rows_b) == 1
                and rows_b[0]["origin"] == "purchase"
                and rows_b[0]["projected_amount"] == exp_amount_b   # ==, no tol
                and rows_b[0]["payment_date"] == date(2027, 1, 9))
        ck("AC-BE9-4/NFR-BE9-3: sin rate => cuota purchase EXACTA (float "
           "==) al calculo pre-cambio y CERO filas internment (BR-INT-05)",
           ok_b, f"rows={row_tuples(rows_b)}")

        # ── AC-BE9-5 / BR-INT-04: rate .25 SIN int-terminos => UNA fila
        # internment al 100 % del costo_int en la fecha de importacion
        # (2026: solo la cuota int anclada; 2027: solo la proveedora).
        rows_c26 = planning.get_carryover_purchase_lines(db, state.src_c, 2026)
        rows_c27 = planning.get_carryover_purchase_lines(db, state.src_c, 2027)
        ok_c = (row_tuples(rows_c26) == [(date(2026, 12, 20), "internment",
                                          60_000_000.0 - 48_000_000.0)]
                and row_tuples(rows_c27) == [(date(2027, 1, 9), "purchase",
                                              48_000_000.0)]
                and all(r["projected_amount"] == 12_000_000.0
                        for r in rows_c26)
                and all(r["projected_amount"] == 48_000_000.0
                        for r in rows_c27))
        ck("AC-BE9-5/BR-INT-04: rate sin terminos int => UNA fila "
           "internment 12M (100 % de costo_int, float exacto) en la ancla; "
           "BR-CO-09 por cuota separa streams por anio",
           ok_c, f"c26={row_tuples(rows_c26)} c27={row_tuples(rows_c27)}")

        # ── NFR-BE9-4 + AC-BE9-6: orden bruto prov->int por fila y rank
        # de empate en el merge final.
        rows_d = planning.get_carryover_purchase_lines(db, state.src_d, 2027)
        exp_raw = [
            (date(2027, 1, 20), "purchase", 8_000_000.0),
            (date(2027, 2, 19), "purchase", 8_000_000.0),
            (date(2027, 1, 20), "internment", 4_000_000.0),
            (date(2027, 2, 19), "internment", 4_000_000.0),
        ]
        ck("NFR-BE9-4: dentro de la fila el stream proveedor se genera "
           "ANTES que el de internacion (orden bruto de "
           "get_carryover_purchase_lines)",
           row_tuples(rows_d) == exp_raw, f"raw={row_tuples(rows_d)}")
        merged_d = planning.build_carryover_payload_lines(
            db, state.src_d, 2026, 2027)
        exp_sorted = [
            (date(2027, 1, 20), "purchase", 8_000_000.0),
            (date(2027, 1, 20), "internment", 4_000_000.0),
            (date(2027, 2, 19), "purchase", 8_000_000.0),
            (date(2027, 2, 19), "internment", 4_000_000.0),
        ]
        ck("AC-BE9-6/BR-CO-10 extendido: empate de fecha efectiva => la "
           "fila 'internment' ordena DESPUES de 'purchase' (rank 3 > 2) "
           "en el merge final",
           row_tuples(merged_d) == exp_sorted,
           f"merged={row_tuples(merged_d)}")

        # ── AC-BE9-5 lineless + NFR-BE9-2 medido: sin Linea resoluble el
        # set batch es vacio => 1 solo SELECT (los 2 queries nuevos se
        # OMITEN) y la compra degrada a cuota unica 100 % pre-BE-S9.
        counter = {"n": 0}

        def _count(conn, cursor, statement, parameters, context,
                   executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                counter["n"] += 1

        from sqlalchemy import event
        event.listen(engine, "before_cursor_execute", _count)
        try:
            counter["n"] = 0
            planning.get_carryover_purchase_lines(db, state.src_x, 2027)
            n_lineless = counter["n"]
            counter["n"] = 0
            rows_main = planning.get_carryover_purchase_lines(
                db, state.src_main, 2027)
            n_full = counter["n"]
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        rows_x = planning.get_carryover_purchase_lines(db, state.src_x, 2026)
        ck("NFR-BE9-2 (medido por eventos SQLAlchemy): +2 queries batch "
           "cuando las compras resuelven Linea (3 totales) y CERO cuando "
           "el set esta vacio (1 solo SELECT, batches omitidos)",
           n_full == 3 and n_lineless == 1,
           f"con={n_full} sin={n_lineless}")
        ck("AC-BE9-5 lineless: compra en CECO sin Linea => pct 0 => cuota "
           "unica 100 % exacta en la ancla y cero filas internment "
           "(comportamiento pre-BE-S9 intacto)",
           len(rows_x) == 1 and rows_x[0]["origin"] == "purchase"
           and rows_x[0]["projected_amount"] == 5_000_000.0
           and rows_x[0]["payment_date"] == date(2026, 12, 10),
           f"rows={row_tuples(rows_x)}")

        # ── Paridad unit-vs-HTTP del ejemplo verbatim (mismo codigo).
        # Se compara contra build_carryover_payload_lines (el merge ya
        # ordenado por BR-CO-10 que sirve la API), no contra el orden
        # bruto de generacion de get_carryover_purchase_lines.
        built_main = planning.build_carryover_payload_lines(
            db, state.src_main, 2026, 2027)
        http_payload = carry_payload(state.tgt) or {}
        ck("Paridad unit-vs-HTTP: build_carryover_payload_lines in-process "
           "coincide con la respuesta de la API (mismo codigo, cero "
           "deriva)",
           [(l["id_cost_center"], l["origin"], l["projected_amount"])
            for l in http_payload.get("lines", [])]
           == [(l.id_cost_center, l.origin, l.projected_amount)
               for l in built_main],
           f"http={len(http_payload.get('lines', []))} "
           f"unit={len(built_main)}")
    finally:
        db.close()
    return True


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Budget INTERNMENT Split Smoke (BE-S9-INTERNMENT-SPLIT)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Banco: Lineas/CECOS desechables + escenarios 'INTERN *' en "
          f"{SRC_YEAR} (anio REAL, ejemplo verbatim §9) -> {TGT_YEAR}")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    if not t02_setup_fixtures():
        print("ABORT: los catalogos de fixture no pudieron crearse")
        postclean()
        return 1
    if not t03_seed_scenarios():
        print("ABORT: los escenarios centinela no pudieron crearse")
        postclean()
        return 1
    print()

    tests = [
        t04_ac_be9_1_rate_catalog,
        t05_ac_be9_2_term_catalog,
        t06_ac_be9_3_end_to_end,
        t07_ac_be9_7_row_intact,
        t08_unit_be9,
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
