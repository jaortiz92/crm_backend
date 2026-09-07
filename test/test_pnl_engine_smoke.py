"""
P&L Engine (Pilar 1) Smoke Tests - spec backend.02_09 v1.2

Verificacion runtime de AC-1..AC-16 (+ AC-9b gate I-2, E-1/E-2 de errores)
contra el golden seed deterministico de §11, con marcador "SMK" para
idempotencia (pre-clean / post-clean garantizados con try/finally).

Cobertura:
  - AC-1   esquema: tabla creada por create_all + GET tasas 200 + import modelo
  - AC-2   CRUD de tasas por API (POST 200, solape 400 E-5, pct=101 422, PUT
           fecha invertida 400 E-4, merge parcial de PUT)
  - AC-3   golden consolidado §6.1.1 (20 valores + meta completa) y §12.2 SQL
  - AC-3b  include_breakdown (Q3b por expense_type)
  - AC-4   D-1: borrar NC-1 => revenues.actual 170000 (y restaurar)
  - AC-5   convencion de rounding: 46.7 (no el 46.6 truncado del HSpec)
  - AC-6   sin presupuesto active => 200, budgets null, warning literal
  - AC-7   escenario via id_budget (clon SQL) => warning "scenario budget"
  - AC-8   BR-15/BR-8 favorability chain al desactivar tasas
  - AC-9   corte por id_line §6.1.2 (not_filterable literal, operating==gross)
  - AC-9b  corte por id_reference => GATE I-2: budgets null (nunca 0.0)
  - AC-10  filtro id_cost_center => BR-9 (revenues no filtrable, eco literal)
  - AC-11  rango sin datos (2027) => ceros y margenes null, 200 OK
  - AC-12  read-only: conteos identicos antes/despues de 5 llamadas
  - AC-13  cash-flow byte-a-byte + stubs budget-vs-actual/tracking intactos
  - AC-14  auth: pnl y tasas sin token => 401/403
  - AC-15  OpenAPI: ruta + response_model PnLResponse + 5 rutas de tasas
  - AC-16  invariante BR-21 en TODAS las respuestas capturadas
  - E-1/E-2 400 fecha invertida / 404 FKs inexistentes
  - Xyear  warning de ano cruzado (match por PREFIJO, ver nota D-1 del informe)

Uso:
    1. docker compose -f docker-compose-dev.yaml up -d
    2. copiar/completar .env_test (USERNAME/PASSWORD)
    3. python test/test_pnl_engine_smoke.py     (desde crm_backend/)

Nota de precision (errata flotante documentada en auditoria estatica):
  AC-3 fija margin_pct_budget=48.1 y 30.6; son empates binarios knife-edge
  (round(48.125,1) seria 48.2 con banker's rounding exacto). Se asercion con
  ==48.1 segun spec; si alguna plataforma devolviera 48.2 es debate de spec
  (§5.3) no bug de esta asercion. Tolerancia numerica general: 1e-9.
"""

import json
import subprocess
import sys
import traceback
from pathlib import Path

import requests
from dotenv import dotenv_values
import psycopg2

# Consolas de Windows (cp1252) no codifican los caracteres graficos del reporte
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ══════════════════════════════════════════════════════════════
# CONFIGURACION (.env_test + .env.development del backend)
# ══════════════════════════════════════════════════════════════

TEST_DIR = Path(__file__).parent
ENV_FILE = TEST_DIR / ".env_test"
DEV_ENV_FILE = TEST_DIR.parent / ".env.development"

if not ENV_FILE.exists():
    print(f"ERROR: No se encontro {ENV_FILE}")
    print("Copia .env_test.example a .env_test y configura tus credenciales")
    sys.exit(1)
if not DEV_ENV_FILE.exists():
    print(f"ERROR: No se encontro {DEV_ENV_FILE} (parametros POSTGRES_* para el seed SQL)")
    sys.exit(1)

config = dotenv_values(ENV_FILE)
dev_config = dotenv_values(DEV_ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')

PG_HOST = (config.get("PG_HOST") or "127.0.0.1").strip('"\'')
PG_PORT = int((config.get("PG_PORT") or "5433").strip('"\''))
PG_USER = (config.get("PG_USER") or dev_config.get("POSTGRES_USER", "postgres")).strip('"\'')
PG_PASSWORD = (config.get("PG_PASSWORD") or dev_config.get("POSTGRES_PASSWORD", "")).strip('"\'')
PG_DB = (config.get("PG_DB") or dev_config.get("POSTGRES_DB", "postgres")).strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# CONSTANTES DEL GOLDEN SEED §11
# ══════════════════════════════════════════════════════════════

MARK = "SMK"                       # marcador de idempotencia
DFROM, DTO = "2026-01-01", "2026-01-31"
RATE_FROM, RATE_TO = "2026-01-01", "2026-12-31"
BUD_NAME = "SMK Presupuesto 2026"
PNL_URL = "/budget/analytics/pnl"
RATES_URL = "/budget/line-cost-rate"
TOL = 1e-9

E4_DETAIL = "date_to must be on or after date_from"
E5_DETAIL = ("Overlapping active rate for this line (or global) period; "
             "deactivate or adjust dates first")
E1_DETAIL = "date_from must be on or before date_to"
NF_REVENUES_CC = "revenues (no cost-center dimension)"
NF_OPEX_SLICE = "opex (no line/reference dimension)"
NF_OPEX_BUDGET = "opex_budget (no slice support in v1)"
NF_REV_BUDGET_REF = "revenues_budget (no reference dimension)"
NF_COGS_BUDGET_REF = "cogs_budget (no reference dimension)"

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.results = []
        # ids del seed (dinamicos)
        self.L1 = self.L2 = self.BRAND = self.REF = None
        self.CCA = self.CCB = self.CCC = None
        self.BUD = self.CLONE = None
        self.RATE_L1 = self.RATE_GLOB = None
        self.INV1 = self.NC1 = None
        # payloads capturados para AC-16 (solo respuestas P&L: dict)
        self.payloads = {}
        self.cashflow_before = None
        # cuarentenas (datos ajenos temporizados, restauradas al final)
        self.quarantined_rate_ids = []
        self.quarantined_budget_ids = []
        self.counts_initial = None

state = TestState()

# ══════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════

def section(title: str):
    print()
    print(f"── {title} " + "─" * max(0, 56 - len(title)))


def ck(name: str, cond: bool, detail: str = "") -> bool:
    state.total += 1
    status = "OK" if cond else "FAIL"
    msg = f"[{state.total:3d}] {name} ... {status}"
    if detail and not cond:
        msg += f"  ({detail})"
    print(msg)
    if cond:
        state.passed += 1
    else:
        state.failed += 1
    state.results.append((name, bool(cond), detail if not cond else ""))
    return bool(cond)


def api(method: str, endpoint: str, auth: bool = True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = dict(state.headers) if auth else {}
    try:
        return requests.request(method, url, headers=headers, timeout=30, **kwargs)
    except requests.exceptions.RequestException:
        return None


def sql_scalar(cur, query, params=None):
    cur.execute(query, params)
    row = cur.fetchone()
    return row[0] if row else None


def sql_exec(cur, query, params=None):
    cur.execute(query, params)


def feq(a, b, tol=TOL):
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= tol


def ck_keys(tag, obj, expected: dict):
    """Asercion campo-a-campo. expected: valor literal; None => debe ser null;
    numeros comparados con tolerancia feq(); str/list/dict con == exacto."""
    if obj is None:
        ck(tag, False, "payload None")
        return False
    ok_all = True
    for k, exp in expected.items():
        got = obj.get(k, "<<missing>>")
        if exp is None:
            ok = got is None
        elif isinstance(exp, (int, float)) and not isinstance(exp, bool):
            ok = got != "<<missing>>" and feq(got, float(exp))
        else:
            ok = got == exp
        ok_all = ck(f"{tag}.{k}", ok, f"esperado={exp!r} obtenido={got!r}") and ok_all
    return ok_all


def pnl_get(cur, params: dict, tag: str):
    """GET /pnl y captura del payload para AC-16. None si fallo."""
    r = api("GET", f"{PNL_URL}?" + "&".join(f"{k}={v}" for k, v in params.items()))
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "sin conexion"
        body = r.text[:200] if r is not None else ""
        ck(tag, False, f"HTTP {code} {body}")
        return None
    data = r.json()
    state.payloads[tag] = data
    return data


def xsql_check(cur, tag, query, expected, params=None):
    """Verificacion SQL cruzada §12.2: el escalar debe coincidir con el payload."""
    got = sql_scalar(cur, query, params)
    return ck(tag, got is not None and feq(float(got), expected),
              f"SQL={got} payload={expected}")


# ══════════════════════════════════════════════════════════════
# FASE 0: LIMPIEZA IDEMPOTENTE (marcador SMK)
# ══════════════════════════════════════════════════════════════

CLEAN_ORDER = [
    ("invoice_details",
     "DELETE FROM invoice_details WHERE id_invoice IN "
     "(SELECT id_invoice FROM invoices WHERE invoice_number LIKE 'SMK%')"),
    ("invoices", "DELETE FROM invoices WHERE invoice_number LIKE 'SMK%'"),
    ("actual_costs", "DELETE FROM actual_costs WHERE document_number LIKE 'SMK%'"),
    ("actual_expenses",
     "DELETE FROM actual_expenses WHERE accounting_account = 'SMK' "
     "OR document_number LIKE 'SMK%'"),
    ("budget_lines",
     "DELETE FROM budget_lines WHERE id_budget IN "
     "(SELECT id_budget FROM budgets WHERE budget_name LIKE 'SMK%')"),
    ("line_cost_rates",
     "DELETE FROM line_cost_rates WHERE rate_name LIKE 'SMK%'"),
    ("budgets (clones)",
     "DELETE FROM budgets WHERE budget_name LIKE 'SMK%' AND parent_budget_id IS NOT NULL"),
    ("budgets", "DELETE FROM budgets WHERE budget_name LIKE 'SMK%'"),
    ("cost_centers", "DELETE FROM cost_centers WHERE cost_center_code LIKE 'SMK%'"),
    ("product_references", "DELETE FROM product_references WHERE reference LIKE 'SMK%'"),
    ("brands", "DELETE FROM brands WHERE brand_name LIKE 'SMK%'"),
    ("lines", "DELETE FROM lines WHERE line_name LIKE 'SMK%'"),
]

COUNT_TABLES = [
    "invoices", "invoice_details", "actual_costs", "actual_expenses",
    "budget_lines", "budgets", "line_cost_rates", "cost_centers",
    "product_references", "brands", "lines",
]


def source_counts(cur):
    out = {}
    for t in COUNT_TABLES:
        out[t] = sql_scalar(cur, f"SELECT count(*) FROM {t}")
    return out


def clean_smk(cur, phase):
    """Post/pre-clean idempotente. Un commit por sentencia: si una borra-
    cion falla no se pierden las ya ejecutadas (lecion del run piloto)."""
    for table, stmt in CLEAN_ORDER:
        try:
            sql_exec(cur, stmt)
            cur.connection.commit()
        except psycopg2.Error as e:
            cur.connection.rollback()
            print(f"  [warn] {phase}: fallo limpiando {table}: "
                  f"{str(e.orig).splitlines()[0][:120]}")


# ══════════════════════════════════════════════════════════════
# CUARENTENA DE CONFLICTOS (datos ajenos al smoke)
# ══════════════════════════════════════════════════════════════

def quarantine_conflicts(cur):
    """Desactiva tasas GLOBALES ajenas vigentes al corte y archiva presupuestos
    ajenos active de 2026/2027 que romperian Q0/BR-13. Se restauran en el finally."""
    cur.execute(
        "SELECT id_line_cost_rate FROM line_cost_rates "
        "WHERE is_active AND id_line IS NULL AND rate_name NOT LIKE 'SMK%' "
        "AND date_from <= '2026-01-31' AND date_to >= '2026-01-31'")
    state.quarantined_rate_ids = [r[0] for r in cur.fetchall()]
    for rid in state.quarantined_rate_ids:
        sql_exec(cur, "UPDATE line_cost_rates SET is_active = FALSE "
                      "WHERE id_line_cost_rate = %s", (rid,))

    cur.execute(
        "SELECT id_budget FROM budgets "
        "WHERE budget_year IN (2026, 2027) AND status = 'active' "
        "AND is_scenario = FALSE AND budget_name NOT LIKE 'SMK%'")
    state.quarantined_budget_ids = [r[0] for r in cur.fetchall()]
    for bid in state.quarantined_budget_ids:
        sql_exec(cur, "UPDATE budgets SET status = 'archived' WHERE id_budget = %s", (bid,))
    cur.connection.commit()
    if state.quarantined_rate_ids or state.quarantined_budget_ids:
        print(f"  [info] cuarentena: {len(state.quarantined_rate_ids)} tasas globales, "
              f"{len(state.quarantined_budget_ids)} presupuestos (se restauran al final)")


def restore_quarantined(cur):
    for rid in state.quarantined_rate_ids:
        try:
            sql_exec(cur, "UPDATE line_cost_rates SET is_active = TRUE "
                          "WHERE id_line_cost_rate = %s", (rid,))
        except psycopg2.Error:
            cur.connection.rollback()
    for bid in state.quarantined_budget_ids:
        try:
            sql_exec(cur, "UPDATE budgets SET status = 'active' WHERE id_budget = %s", (bid,))
        except psycopg2.Error:
            cur.connection.rollback()
    cur.connection.commit()


# ══════════════════════════════════════════════════════════════
# SEED GOLDEN §11 (SQL directo; tasas van por API en AC-2)
# ══════════════════════════════════════════════════════════════
#
# IMPORTANTE: en esta BD dev los datos operativos se cargaron por ETL con
# ids explicitos y las secuencias (nextval) quedaron desincronizadas
# (p.ej. nextval('lines_id_line_seq')=1 con 8 filas existentes). El seed
# usa MAX+1 explicito — tecnica del propio ETL — sin tocar secuencias ajenas.
# La tabla nueva line_cost_rates esta vacia, asi que las tasas por API si
# usan su secuencia sin colision.

def next_id(cur, table, pk):
    return int(sql_scalar(cur, f"SELECT coalesce(max({pk}), 0) + 1 FROM {table}"))


def seed_catalogs(cur):
    lid = next_id(cur, "lines", "id_line")
    sql_exec(cur, "INSERT INTO lines (id_line, line_name) VALUES (%s, 'SMK L1')", (lid,))
    state.L1 = lid
    lid = next_id(cur, "lines", "id_line")
    sql_exec(cur, "INSERT INTO lines (id_line, line_name) VALUES (%s, 'SMK L2')", (lid,))
    state.L2 = lid
    bid = next_id(cur, "brands", "id_brand")
    sql_exec(cur, "INSERT INTO brands (id_brand, brand_name, id_line) "
                  "VALUES (%s, 'SMK BRAND-X', %s)", (bid, state.L1))
    state.BRAND = bid
    # product_references NOT NULL: reference, id_brand, gender (label 'U'), value_base
    rid = next_id(cur, "product_references", "id_reference")
    sql_exec(cur, "INSERT INTO product_references (id_reference, reference, id_brand, "
                  "gender, value_base) VALUES (%s, 'SMK REF R1', %s, 'U', 100000)",
             (rid, state.BRAND))
    state.REF = rid
    # CECO A (id_line=L1), B (sin linea -> global), C (L2, sin tasa; sin filas de
    # presupuesto en §11, por eso no aparece en la traza)
    cid = next_id(cur, "cost_centers", "id_cost_center")
    sql_exec(cur, "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
                  "cost_center_name, id_line) VALUES (%s, 'SMK-A', 'SMK CECO A', %s)",
             (cid, state.L1))
    state.CCA = cid
    cid = next_id(cur, "cost_centers", "id_cost_center")
    sql_exec(cur, "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
                  "cost_center_name, id_line) VALUES (%s, 'SMK-B', 'SMK CECO B', NULL)", (cid,))
    state.CCB = cid
    cid = next_id(cur, "cost_centers", "id_cost_center")
    sql_exec(cur, "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
                  "cost_center_name, id_line) VALUES (%s, 'SMK-C', 'SMK CECO C', %s)",
             (cid, state.L2))
    state.CCC = cid
    cur.connection.commit()


def seed_budget(cur):
    """Presupuesto en status draft; se activa tras el seed para no contaminar."""
    bid = next_id(cur, "budgets", "id_budget")
    sql_exec(cur, "INSERT INTO budgets (id_budget, budget_name, budget_year, "
                  "budget_period, status, is_scenario) "
                  "VALUES (%s, %s, 2026, 'annual', 'draft', FALSE)", (bid, BUD_NAME))
    state.BUD = bid
    # Enumes nativos PG guardan NAMES: 'INCOME'/'EXPENSE', 'FIXED' (verificado en
    # el recon; I-7 documenta la trampa del default 'fixed')
    for cc, ltype, amount in ((state.CCA, "INCOME", 100000), (state.CCB, "INCOME", 60000),
                              (state.CCA, "EXPENSE", 15000), (state.CCB, "EXPENSE", 13000)):
        lid = next_id(cur, "budget_lines", "id_budget_line")
        sql_exec(cur,
            "INSERT INTO budget_lines (id_budget_line, id_budget, id_cost_center, "
            "line_type, budget_date, projected_amount, description, behavior_type) "
            "VALUES (%s, %s, %s, %s, '2026-01-15', %s, 'SMK', 'FIXED')",
            (lid, state.BUD, cc, ltype, amount))
    cur.connection.commit()


def insert_invoice(cur, num, inv_date, total):
    iid = next_id(cur, "invoices", "id_invoice")
    sql_exec(cur,
        "INSERT INTO invoices (id_invoice, invoice_number, invoice_date, "
        "total_quantities, total_without_tax, total_discount, total_with_tax) "
        "VALUES (%s, %s, %s, %s, %s, 0, %s)",
        (iid, num, inv_date, 1 if total > 0 else -1, total, total * 1.19))
    did = next_id(cur, "invoice_details", "id_invoice_detail")
    sql_exec(cur,
        "INSERT INTO invoice_details (id_invoice_detail, id_invoice, id_reference, "
        "product, description, color, size, id_brand, gender, unit_value, quantity, "
        "value_without_tax, discount, value_with_tax) "
        "VALUES (%s, %s, %s, 'SMK', 'SMK detail', 'U', 'U', %s, 'U', %s, %s, %s, 0, %s)",
        (did, iid, state.REF, state.BRAND, abs(total), 1 if total > 0 else -1,
         total, total * 1.19))
    return iid


def delete_invoice(cur, inv_id):
    sql_exec(cur, "DELETE FROM invoice_details WHERE id_invoice = %s", (inv_id,))
    sql_exec(cur, "DELETE FROM invoices WHERE id_invoice = %s", (inv_id,))


def seed_execution(cur):
    state.INV1 = insert_invoice(cur, "SMK-INV-1", "2026-01-15", 170000)
    # D-1: NC = factura negativa con detalle negativo Y id_reference poblado (§13)
    state.NC1 = insert_invoice(cur, "SMK-NC-1", "2026-01-20", -20000)
    for doc, ref, amount in (("SMK-C1", state.REF, 50000), ("SMK-C2", None, 30000)):
        cid = next_id(cur, "actual_costs", "id_actual_cost")
        sql_exec(cur,
            "INSERT INTO actual_costs (id_actual_cost, id_cost_center, id_reference, "
            "document_number, cost_date, cost_type, quantity, unit_cost, amount, "
            "description) VALUES (%s, %s, %s, %s, '2026-01-15', 'MATERIA PRIMA', "
            "1, %s, %s, 'SMK')", (cid, state.CCA, ref, doc, amount, amount))
    for doc, cc, etype, amount in (("SMK-R1", state.CCA, "NOMINAS", 18000),
                                   ("SMK-R2", state.CCB, "ARRENDAMIENTO", 12000)):
        eid = next_id(cur, "actual_expenses", "id_actual_expense")
        sql_exec(cur,
            "INSERT INTO actual_expenses (id_actual_expense, id_cost_center, "
            "accounting_account, expense_date, expense_type, amount, "
            "document_number, description) "
            "VALUES (%s, %s, 'SMK', '2026-01-15', %s, %s, %s, 'SMK')",
            (eid, cc, etype, amount, doc))
    cur.connection.commit()


def clone_budget_for_ac7(cur):
    cid = next_id(cur, "budgets", "id_budget")
    sql_exec(cur,
        "INSERT INTO budgets (id_budget, budget_name, budget_year, budget_period, "
        "status, is_scenario, parent_budget_id) "
        "SELECT %s, 'SMK CLONE 2026', budget_year, budget_period, 'draft', TRUE, id_budget "
        "FROM budgets WHERE id_budget = %s", (cid, state.BUD))
    state.CLONE = cid
    sql_exec(cur,
        "INSERT INTO budget_lines (id_budget_line, id_budget, id_cost_center, line_type, "
        "budget_date, projected_amount, description, behavior_type) "
        "SELECT coalesce((SELECT max(id_budget_line) FROM budget_lines), 0) + "
        "row_number() OVER (), %s, id_cost_center, line_type, budget_date, "
        "projected_amount, description, behavior_type "
        "FROM budget_lines WHERE id_budget = %s", (state.CLONE, state.BUD))
    cur.connection.commit()
    return state.CLONE


# ══════════════════════════════════════════════════════════════
# HELPERS DE TASAS POR API (§6.2)
# ══════════════════════════════════════════════════════════════

def rate_post(body):
    return api("POST", f"{RATES_URL}/", json=body)


def rate_put(rid, body):
    return api("PUT", f"{RATES_URL}/{rid}", json=body)


# ══════════════════════════════════════════════════════════════
# AC-16: invariante BR-21 sobre toda respuesta capturada
# ══════════════════════════════════════════════════════════════

def br21_all():
    section("AC-16 - invariante BR-21 en todas las respuestas")
    for tag, data in state.payloads.items():
        cogs_b = data["pnl_statement"]["cogs"]["budget"]
        trace = data["meta"]["cogs_budget_trace"]
        if cogs_b is None:
            ck(f"{tag}:BR21 null⇒trace[]", trace == [], f"trace={trace}")
        else:
            s = round(sum(t["cogs_contribution"] for t in trace), 2)
            ck(f"{tag}:BR21 Σcontrib==cogs.budget", feq(s, cogs_b),
               f"Σ={s} cogs.budget={cogs_b}")
            ck(f"{tag}:BR21 source∈(line,global)",
               all(t["source"] in ("line", "global") for t in trace))


# ══════════════════════════════════════════════════════════════
# PRUEBAS AC-1 .. AC-15
# ══════════════════════════════════════════════════════════════

def ac01(cur):
    section("AC-1 - esquema (tabla, GET 200 [], import del modelo)")
    reg = sql_scalar(cur, "SELECT to_regclass('public.line_cost_rates')::text")
    ck("AC-1 tabla line_cost_rates existe (create_all)", reg == "line_cost_rates",
       f"to_regclass={reg}")
    cols = [r[0] for r in
            (cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'line_cost_rates' ORDER BY ordinal_position"),
             cur.fetchall())[1]]
    ck("AC-1 columnas del modelo",
       set(cols) == {"id_line_cost_rate", "id_line", "rate_name", "cogs_pct",
                     "date_from", "date_to", "is_active", "created_at", "updated_at"},
       f"cols={cols}")
    n_rates_before = sql_scalar(cur, "SELECT count(*) FROM line_cost_rates")
    r = api("GET", f"{RATES_URL}/")
    ck("AC-1 GET /budget/line-cost-rate/ ⇒ 200", r is not None and r.status_code == 200)
    if r is not None and r.status_code == 200:
        ck("AC-1 lista vacía con tabla vacía (AC-1 literal)" if n_rates_before == 0
           else "AC-1 lista coherente con conteo",
           len(r.json()) == n_rates_before)
    try:
        p = subprocess.run(
            ["docker", "exec", "crm_backend_dev", "python", "-c",
             "from app.models.budget import LineCostRate; print('IMPORT_OK')"],
            capture_output=True, text=True, timeout=120)
        ck("AC-1 from app.models.budget import LineCostRate (en contenedor)",
           "IMPORT_OK" in p.stdout, (p.stderr or p.stdout)[:120])
    except FileNotFoundError:
        ck("AC-1 import del modelo (docker CLI no disponible)", False,
           "docker no está en el PATH del host")


def do_login():
    section("Login (POST /login/)")
    r = api("POST", "/login/", auth=False, json={"username": USERNAME, "password": PASSWORD})
    if r is not None and r.status_code == 200:
        state.token = r.json().get("access_token")
        state.headers = {"Authorization": f"Bearer {state.token}"}
        ck("Login JWT", bool(state.token))
        return True
    ck("Login JWT", False, f"status={r.status_code if r is not None else 'sin conexion'}")
    return False


def ac02(cur):
    section("AC-2 - ciclo de vida de tasas por API")
    r = rate_post({"id_line": state.L1, "rate_name": "SMK L1 2026",
                   "cogs_pct": 50.00, "date_from": RATE_FROM, "date_to": RATE_TO})
    ok = r is not None and r.status_code == 200
    ck("AC-2 POST L1 50% ⇒ 200", ok, r.text[:120] if r is not None else "sin conexion")
    if ok:
        state.RATE_L1 = r.json()["id_line_cost_rate"]

    r = rate_post({"id_line": state.L1, "rate_name": "SMK L1 OVERLAP",
                   "cogs_pct": 60.00, "date_from": "2026-06-01", "date_to": RATE_TO})
    ck("AC-2 POST solape misma línea ⇒ 400 (E-5)",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E5_DETAIL,
       f"status={r.status_code if r is not None else '?'} detail={r.json().get('detail')[:80] if r is not None else ''}")

    r = rate_post({"id_line": None, "rate_name": "SMK GLOBAL 2026",
                   "cogs_pct": 55.00, "date_from": RATE_FROM, "date_to": RATE_TO})
    ok = r is not None and r.status_code == 200
    ck("AC-2 POST global 55% (id_line NULL) ⇒ 200", ok)
    if ok:
        state.RATE_GLOB = r.json()["id_line_cost_rate"]

    r = rate_post({"id_line": None, "rate_name": "SMK GLOBAL OVERLAP",
                   "cogs_pct": 60.00, "date_from": "2026-02-01", "date_to": RATE_TO})
    ck("AC-2 POST solape GLOBAL NULL-safe ⇒ 400 (E-5, .is_(None))",
       r is not None and r.status_code == 400 and r.json().get("detail") == E5_DETAIL)

    r = rate_post({"id_line": state.L1, "rate_name": "SMK BAD PCT",
                   "cogs_pct": 101, "date_from": RATE_FROM, "date_to": RATE_TO})
    ck("AC-2 POST cogs_pct=101 ⇒ 422 (E-3/BR-12)",
       r is not None and r.status_code == 422)

    r = rate_put(state.RATE_GLOB, {"date_to": "2025-12-31"})
    ck("AC-2 PUT fecha invertida ⇒ 400 (E-4)",
       r is not None and r.status_code == 400 and r.json().get("detail") == E4_DETAIL,
       f"status={r.status_code if r is not None else '?'}")

    r = api("GET", f"{RATES_URL}/{state.RATE_GLOB}")
    ck("AC-2 PUT 400 no mutó la fila (sigue 2026-12-31)",
       r is not None and r.status_code == 200 and r.json()["date_to"] == RATE_TO)

    r = rate_put(state.RATE_GLOB, {"rate_name": "SMK GLOBAL 2026-R"})
    ck("AC-2 PUT merge parcial (solo rate_name; pct intacto 55.0)",
       r is not None and r.status_code == 200
       and r.json()["rate_name"] == "SMK GLOBAL 2026-R" and feq(r.json()["cogs_pct"], 55.0))

    r = api("GET", f"{RATES_URL}/?active_only=true&date=2026-01-31")
    ck("AC-2 GET ?active_only&date ⇒ 2 vigentes",
       r is not None and r.status_code == 200 and len(r.json()) == 2)


def ac13_baseline(cur):
    section("AC-13 - baseline cash-flow y stubs (antes de la batería P&L)")
    r = api("GET", "/budget/analytics/cash-flow-projection?budget_year=2026")
    if r is not None and r.status_code == 200:
        state.cashflow_before = json.dumps(r.json(), sort_keys=True)
        ck("AC-13 cash-flow responde 200", True)
    else:
        state.cashflow_before = None
        ck("AC-13 cash-flow responde 200", False,
           f"status={r.status_code if r is not None else 'sin conexion'}")
    r = api("GET", "/budget/analytics/budget-vs-actual?id_budget=1")
    ck("AC-13 stub budget-vs-actual ⇒ 200 []",
       r is not None and r.status_code == 200 and r.json() == [])
    r = api("GET", "/budget/analytics/tracking/1")
    stub = r is not None and r.status_code == 200 and r.json().get("budget_name") == "" \
        and r.json().get("total_budgeted") in (0, 0.0)
    ck("AC-13 stub tracking ⇒ 200 con forma stub", stub,
       r.text[:120] if r is not None else "sin conexion")


def ac03(cur):
    section("AC-3/AC-5 - golden consolidado §6.1.1")
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-3")
    if data is None:
        return
    st = data["pnl_statement"]
    ck_keys("AC-3 revenues", st["revenues"],
            {"actual": 150000.0, "budget": 160000.0, "variance": -10000.0, "variance_pct": -6.25})
    ck_keys("AC-3 cogs", st["cogs"],
            {"actual": 80000.0, "budget": 83000.0, "variance": 3000.0, "variance_pct": 3.61})
    ck_keys("AC-3 gross_profit", st["gross_profit"],
            {"actual": 70000.0, "budget": 77000.0, "variance": -7000.0, "variance_pct": -9.09,
             "margin_pct": 46.7, "margin_pct_budget": 48.1})
    ck_keys("AC-3 opex", st["opex"],
            {"actual": 30000.0, "budget": 28000.0, "variance": -2000.0, "variance_pct": -7.14,
             "breakdown": None})
    ck_keys("AC-3 operating_profit", st["operating_profit"],
            {"actual": 40000.0, "budget": 49000.0, "variance": -9000.0, "variance_pct": -18.37,
             "margin_pct": 26.7, "margin_pct_budget": 30.6})
    ck("AC-5 convención rounding (margin 70000/150000 ⇒ 46.7, no 46.6)",
       feq(st["gross_profit"]["margin_pct"], 46.7), f"got={st['gross_profit']['margin_pct']}")

    meta = data["meta"]
    ck("AC-3 period {'from','to'}", data["period"] == {"from": DFROM, "to": DTO})
    ck("AC-3 meta.mode consolidated", meta["mode"] == "consolidated")
    ck_keys("AC-3 meta.budget_source", meta["budget_source"],
            {"id_budget": state.BUD, "budget_name": BUD_NAME, "status": "active"})
    ck("AC-3 meta.filters eco exacto", meta["filters"] == {
        "date_from": DFROM, "date_to": DTO, "id_budget": None, "id_cost_center": None,
        "id_line": None, "id_reference": None, "include_breakdown": False})
    ck("AC-3 meta.not_filterable == []", meta["not_filterable"] == [])
    ck("AC-3 meta.warnings == []", meta["warnings"] == [], f"got={meta['warnings']}")

    tr = sorted(meta["cogs_budget_trace"], key=lambda i: i["id_cost_center"])
    ck("AC-3 trace 2 ítems", len(tr) == 2, f"got={tr}")
    if len(tr) == 2:
        ck_keys("AC-3 trace[cc A]", tr[0],
                {"id_cost_center": state.CCA, "cost_center_code": "SMK-A",
                 "id_line": state.L1, "pct": 50.0, "source": "line",
                 "income_budget": 100000.0, "cogs_contribution": 50000.0})
        ck_keys("AC-3 trace[cc B]", tr[1],
                {"id_cost_center": state.CCB, "cost_center_code": "SMK-B",
                 "id_line": None, "pct": 55.0, "source": "global",
                 "income_budget": 60000.0, "cogs_contribution": 33000.0})

    # §12.2 verificacion SQL cruzada de cada linea del payload
    xsql_check(cur, "AC-3 SQL× revenues",
               "SELECT coalesce(sum(total_without_tax),0) FROM invoices "
               "WHERE invoice_date BETWEEN %s AND %s", 150000, (DFROM, DTO))
    xsql_check(cur, "AC-3 SQL× cogs",
               "SELECT coalesce(sum(amount),0) FROM actual_costs "
               "WHERE cost_date BETWEEN %s AND %s", 80000, (DFROM, DTO))
    xsql_check(cur, "AC-3 SQL× opex",
               "SELECT coalesce(sum(amount),0) FROM actual_expenses "
               "WHERE expense_date BETWEEN %s AND %s", 30000, (DFROM, DTO))
    xsql_check(cur, "AC-3 SQL× budget ingresos",
               "SELECT coalesce(sum(bl.projected_amount),0) FROM budget_lines bl "
               "JOIN budgets b ON b.id_budget = bl.id_budget "
               "WHERE b.budget_year = 2026 AND b.status = 'active' "
               "AND b.is_scenario = FALSE AND bl.line_type = 'INCOME' "
               "AND bl.budget_date BETWEEN %s AND %s", 160000, (DFROM, DTO))


def ac03b(cur):
    section("AC-3b - include_breakdown (Q3b)")
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO, "include_breakdown": "true"},
                   "AC-3b")
    if data is None:
        return
    bd = data["pnl_statement"]["opex"]["breakdown"] or []
    by_cat = {i["category"]: i for i in bd}
    ck("AC-3b breakdown tiene las 2 categorías", set(by_cat) == {"NOMINAS", "ARRENDAMIENTO"},
       f"got={bd}")
    if "NOMINAS" in by_cat:
        ck("AC-3b NOMINAS == 18000", feq(by_cat["NOMINAS"]["actual"], 18000.0),
           f"got={by_cat['NOMINAS']}")
    if "ARRENDAMIENTO" in by_cat:
        ck("AC-3b ARRENDAMIENTO == 12000", feq(by_cat["ARRENDAMIENTO"]["actual"], 12000.0),
           f"got={by_cat['ARRENDAMIENTO']}")
    ck("AC-3b opex.actual sigue 30000", feq(data["pnl_statement"]["opex"]["actual"], 30000.0))


def ac09_slice_line(cur):
    section("AC-9 - corte por id_line §6.1.2")
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO, "id_line": state.L1}, "AC-9")
    if data is None:
        return
    st = data["pnl_statement"]
    ck_keys("AC-9 revenues", st["revenues"],
            {"actual": 150000.0, "budget": 100000.0, "variance": 50000.0, "variance_pct": 50.0})
    ck_keys("AC-9 cogs", st["cogs"],
            {"actual": 50000.0, "budget": 50000.0, "variance": 0.0, "variance_pct": 0.0})
    ck_keys("AC-9 gross_profit", st["gross_profit"],
            {"actual": 100000.0, "budget": 50000.0, "variance": 50000.0,
             "variance_pct": 100.0, "margin_pct": 66.7, "margin_pct_budget": 50.0})
    ck_keys("AC-9 opex (null en slice)", st["opex"],
            {"actual": None, "budget": None, "variance": None, "variance_pct": None,
             "breakdown": None})
    ck_keys("AC-9 operating==gross (BR-11)", st["operating_profit"],
            {"actual": 100000.0, "budget": None, "variance": None, "variance_pct": None,
             "margin_pct": 66.7, "margin_pct_budget": None})
    meta = data["meta"]
    ck("AC-9 mode=slice", meta["mode"] == "slice")
    ck("AC-9 not_filterable literal §6.1.2",
       meta["not_filterable"] == [NF_OPEX_SLICE, NF_OPEX_BUDGET], f"got={meta['not_filterable']}")
    ck("AC-9 warnings == [] (NC del seed trae referencia ⇒ sin warning D-1)",
       meta["warnings"] == [], f"got={meta['warnings']}")
    tr = meta["cogs_budget_trace"]
    ck("AC-9 trace solo cc A", len(tr) == 1 and tr[0]["id_cost_center"] == state.CCA
       and tr[0]["source"] == "line", f"got={tr}")
    # SQL cruzada slice (BR-4 detalles; fila sin referencia fuera del JOIN)
    xsql_check(cur, "AC-9 SQL× revenues slice",
               "SELECT coalesce(sum(d.value_without_tax),0) FROM invoice_details d "
               "JOIN invoices i ON i.id_invoice = d.id_invoice "
               "JOIN product_references pr ON pr.id_reference = d.id_reference "
               "JOIN brands br ON br.id_brand = pr.id_brand "
               "WHERE br.id_line = %s AND i.invoice_date BETWEEN %s AND %s",
               150000, (state.L1, DFROM, DTO))
    xsql_check(cur, "AC-9 SQL× cogs slice",
               "SELECT coalesce(sum(c.amount),0) FROM actual_costs c "
               "JOIN product_references pr ON pr.id_reference = c.id_reference "
               "JOIN brands br ON br.id_brand = pr.id_brand "
               "WHERE br.id_line = %s AND c.cost_date BETWEEN %s AND %s",
               50000, (state.L1, DFROM, DTO))


def ac09b_slice_reference(cur):
    section("AC-9b - corte por id_reference: GATE I-2 (budgets null, nunca 0.0)")
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO, "id_reference": state.REF},
                   "AC-9b")
    if data is None:
        return
    st = data["pnl_statement"]
    ck("AC-9b revenues.budget is None (BR-11/I-2, no 0.0)",
       st["revenues"]["budget"] is None, f"got={st['revenues']['budget']!r}")
    ck("AC-9b cogs.budget is None", st["cogs"]["budget"] is None)
    ck("AC-9b opex.budget is None", st["opex"]["budget"] is None)
    ck("AC-9b gross.budget is None (BR-8)", st["gross_profit"]["budget"] is None)
    ck("AC-9b operating.budget is None (BR-8)", st["operating_profit"]["budget"] is None)
    ck_keys("AC-9b actuals", st["revenues"], {"actual": 150000.0, "variance": None})
    ck("AC-9b cogs.actual 50000 (fila 30000 sin referencia fuera)",
       feq(st["cogs"]["actual"], 50000.0), f"got={st['cogs']['actual']}")
    meta = data["meta"]
    ck("AC-9b not_filterable incluye los 4 strings",
       meta["not_filterable"] == [NF_OPEX_SLICE, NF_OPEX_BUDGET,
                                  NF_REV_BUDGET_REF, NF_COGS_BUDGET_REF],
       f"got={meta['not_filterable']}")
    ck("AC-9b trace == []", meta["cogs_budget_trace"] == [])


def ac10_cc_filter(cur):
    section("AC-10 - filtro id_cost_center (BR-9)")
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO, "id_cost_center": state.CCA},
                   "AC-10")
    if data is None:
        return
    st = data["pnl_statement"]
    ck("AC-10 revenues.actual sigue consolidado 150000 (BR-9)",
       feq(st["revenues"]["actual"], 150000.0))
    ck("AC-10 not_filterable ∋ revenues cc",
       data["meta"]["not_filterable"] == [NF_REVENUES_CC],
       f"got={data['meta']['not_filterable']}")
    ck("AC-10 mode consolidated", data["meta"]["mode"] == "consolidated")
    ck_keys("AC-10 revenues (budget A-only)", st["revenues"],
            {"budget": 100000.0, "variance": 50000.0, "variance_pct": 50.0})
    ck_keys("AC-10 cogs (A-only)", st["cogs"],
            {"actual": 80000.0, "budget": 50000.0})
    ck_keys("AC-10 opex (cc A)", st["opex"],
            {"actual": 18000.0, "budget": 15000.0, "variance": -3000.0, "variance_pct": -20.0})
    ck("AC-10 operating actual = 70000−18000 = 52000",
       feq(st["operating_profit"]["actual"], 52000.0))
    tr = data["meta"]["cogs_budget_trace"]
    ck("AC-16-explícito: trace exactamente 1 ítem (cc A, source line)",
       len(tr) == 1 and tr[0]["id_cost_center"] == state.CCA and tr[0]["source"] == "line",
       f"got={tr}")


def acx_year_cross(cur):
    section("Extra - warning año cruzado (prefijo, errata D-1) + resolución año(date_to)")
    data = pnl_get(cur, {"date_from": "2025-12-01", "date_to": DTO}, "Xyear")
    if data is None:
        return
    w = data["meta"]["warnings"]
    ck("Xyear warning por PREFIJO", any(s.startswith("period crosses fiscal years") for s in w),
       f"warnings={w}")
    ck("Xyear presupuesto resuelto = active de 2026 (D-3)",
       feq(data["pnl_statement"]["revenues"]["budget"], 160000.0))


def ac06_no_budget(cur):
    section("AC-6 - sin presupuesto active (E-6: 200 + nulls, nunca 500)")
    sql_exec(cur, "UPDATE budgets SET status = 'archived' WHERE id_budget = %s", (state.BUD,))
    cur.connection.commit()
    try:
        data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-6")
        if data is not None:
            st = data["pnl_statement"]
            null_budgets = all(
                st[k]["budget"] is None for k in
                ("revenues", "cogs", "gross_profit", "opex", "operating_profit"))
            ck("AC-6 todos los budgets null", null_budgets)
            ck("AC-6 todos los variance/variance_pct null",
               all(st[k]["variance"] is None and st[k]["variance_pct"] is None
                   for k in st))
            ck("AC-6 margin_pct_budget null pero margin_pct real intacto",
               st["gross_profit"]["margin_pct_budget"] is None
               and feq(st["gross_profit"]["margin_pct"], 46.7))
            ck("AC-6 actuals intactos (150000/80000/70000/30000/40000)",
               feq(st["revenues"]["actual"], 150000.0)
               and feq(st["cogs"]["actual"], 80000.0)
               and feq(st["gross_profit"]["actual"], 70000.0)
               and feq(st["opex"]["actual"], 30000.0)
               and feq(st["operating_profit"]["actual"], 40000.0))
            ck("AC-6 budget_source null", data["meta"]["budget_source"] is None)
            ck("AC-6 warning literal", data["meta"]["warnings"] ==
               ["No active non-scenario budget for 2026"], f"got={data['meta']['warnings']}")
            ck("AC-6 trace == []", data["meta"]["cogs_budget_trace"] == [])
    finally:
        sql_exec(cur, "UPDATE budgets SET status = 'active' WHERE id_budget = %s", (state.BUD,))
        cur.connection.commit()


def ac07_scenario(cur):
    section("AC-7 - comparación contra escenario clonado (BR-17)")
    clone = clone_budget_for_ac7(cur)
    try:
        data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO, "id_budget": clone}, "AC-7")
        if data is not None:
            ck("AC-7 warning 'Comparing against scenario budget'",
               "Comparing against scenario budget" in data["meta"]["warnings"],
               f"got={data['meta']['warnings']}")
            ck("AC-7 usa el clon (budget_source = id del clon)",
               data["meta"]["budget_source"] and data["meta"]["budget_source"]["id_budget"] == clone)
            ck("AC-7 sin warning 'More than one' (el default sigue siendo el original)",
               not any("More than one" in w for w in data["meta"]["warnings"]))
            ck("AC-7 valores == golden (mismas líneas)",
               feq(data["pnl_statement"]["cogs"]["budget"], 83000.0))
    finally:
        # borrar el clon YA: project_cash_flow no filtra is_scenario, y dejarlo
        # vivo contaminaria el baseline byte-a-byte de AC-13
        sql_exec(cur, "DELETE FROM budget_lines WHERE id_budget = %s", (clone,))
        sql_exec(cur, "DELETE FROM budgets WHERE id_budget = %s", (clone,))
        cur.connection.commit()


def ac08_rate_lifecycle(cur):
    section("AC-8 - BR-15/BR-8: desactivar global y luego L1")
    r = rate_put(state.RATE_GLOB, {"is_active": False})
    ok1 = r is not None and r.status_code == 200
    ck("AC-8 PUT global is_active=false ⇒ 200", ok1)
    if not ok1:
        return
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-8a")
    if data is None:
        return
    st = data["pnl_statement"]
    ck("AC-8a cogs.budget == 50000 (solo cc A)", feq(st["cogs"]["budget"], 50000.0),
       f"got={st['cogs']['budget']}")
    ck("AC-8a gross.budget==110000 y operating.budget==82000 (cadena viva, BR-8)",
       feq(st["gross_profit"]["budget"], 110000.0)
       and feq(st["operating_profit"]["budget"], 82000.0))
    ck("AC-8a warning literal de exclusión del cc B",
       data["meta"]["warnings"] ==
       [f"Cost center {state.CCB} has income budget 60000.00 and no applicable "
        "cost rate; excluded from cogs.budget"],
       f"got={data['meta']['warnings']}")
    tr = data["meta"]["cogs_budget_trace"]
    ck("AC-8a trace reducido al cc A",
       len(tr) == 1 and tr[0]["id_cost_center"] == state.CCA, f"got={tr}")

    r = rate_put(state.RATE_L1, {"is_active": False})
    ok2 = r is not None and r.status_code == 200
    ck("AC-8 PUT L1 is_active=false ⇒ 200", ok2)
    if not ok2:
        return
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-8b")
    if data is None:
        return
    st = data["pnl_statement"]
    ck("AC-8b favorability chain: cogs/gross/operating budgets null (BR-8)",
       st["cogs"]["budget"] is None and st["gross_profit"]["budget"] is None
       and st["operating_profit"]["budget"] is None)
    ck("AC-8b revenues.budget 160000 y opex.budget 28000 sobreviven",
       feq(st["revenues"]["budget"], 160000.0) and feq(st["opex"]["budget"], 28000.0))
    ck("AC-8b warning ausencia total de tasas + exclusiones por CECO (§6.1.3)",
       "No cost rate configured (line or global) for the period: cogs.budget is null"
       in data["meta"]["warnings"]
       and f"Cost center {state.CCA} has income budget 100000.00 and no applicable "
           "cost rate; excluded from cogs.budget" in data["meta"]["warnings"]
       and f"Cost center {state.CCB} has income budget 60000.00 and no applicable "
           "cost rate; excluded from cogs.budget" in data["meta"]["warnings"]
       and len(data["meta"]["warnings"]) == 3,
       f"got={data['meta']['warnings']}")
    ck("AC-8b trace == [] con cogs.budget null", data["meta"]["cogs_budget_trace"] == [])

    rate_put(state.RATE_GLOB, {"is_active": True})
    r = rate_put(state.RATE_L1, {"is_active": True})
    ck("AC-8 reactivación de ambas tasas ⇒ 200", r is not None and r.status_code == 200)
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-8c")
    ck("AC-8 estado golden restaurado (cogs.budget 83000)",
       data is not None and feq(data["pnl_statement"]["cogs"]["budget"], 83000.0))


def ac04_returns(cur):
    section("AC-4 - D-1: NC negativa resta dentro de la sumatoria")
    delete_invoice(cur, state.NC1)
    cur.connection.commit()
    try:
        data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-4")
        if data is not None:
            ck("AC-4 sin NC-1 ⇒ revenues.actual == 170000",
               feq(data["pnl_statement"]["revenues"]["actual"], 170000.0),
               f"got={data['pnl_statement']['revenues']['actual']}")
            ck("AC-4 sin línea separada de devoluciones en el statement",
               "sales_returns" not in data["pnl_statement"])
    finally:
        state.NC1 = insert_invoice(cur, "SMK-NC-1", "2026-01-20", -20000)
        cur.connection.commit()
    data = pnl_get(cur, {"date_from": DFROM, "date_to": DTO}, "AC-4-restore")
    ck("AC-4 NC restaurada ⇒ 150000 de nuevo",
       data is not None and feq(data["pnl_statement"]["revenues"]["actual"], 150000.0))


def ac11_zero_margin(cur):
    section("AC-11 - periodo sin datos (2027): ceros y márgenes null")
    data = pnl_get(cur, {"date_from": "2027-01-01", "date_to": "2027-01-31"}, "AC-11")
    if data is None:
        return
    st = data["pnl_statement"]
    ck("AC-11 todos los actuals == 0.0",
       all(feq(st[k]["actual"], 0.0) for k in ("revenues", "cogs", "gross_profit",
                                               "opex", "operating_profit")))
    ck("AC-11 margin_pct null sin ZeroDivisionError",
       st["gross_profit"]["margin_pct"] is None
       and st["operating_profit"]["margin_pct"] is None)
    ck("AC-11 budgets null (no hay presupuesto 2027) + warning",
       all(st[k]["budget"] is None for k in st)
       and "No active non-scenario budget for 2027" in data["meta"]["warnings"],
       f"warnings={data['meta']['warnings']}")


def ac12_readonly(cur):
    section("AC-12 - motor 100% lectura (conteos antes/después)")
    before = source_counts(cur)
    ok_http = all(api("GET", f"{PNL_URL}?date_from={DFROM}&date_to={DTO}") is not None
                  and api("GET", f"{PNL_URL}?date_from={DFROM}&date_to={DTO}").status_code == 200
                  for _ in range(5))
    ck("AC-12 5 llamadas GET /pnl responden 200", ok_http)
    after = source_counts(cur)
    ck("AC-12 conteos idénticos en las 11 tablas fuente", before == after,
       f"before={before} after={after}")


def ac13_final(cur):
    section("AC-13 - cash-flow byte-a-byte tras toda la batería")
    r = api("GET", "/budget/analytics/cash-flow-projection?budget_year=2026")
    after = json.dumps(r.json(), sort_keys=True) if r is not None and r.status_code == 200 else None
    ck("AC-13 cash-flow idéntico antes/después (regresión budgetEngine)",
       after is not None and after == state.cashflow_before)
    r = api("GET", "/budget/analytics/budget-vs-actual?id_budget=1")
    ck("AC-13 stub budget-vs-actual sigue []",
       r is not None and r.status_code == 200 and r.json() == [])
    r = api("GET", "/budget/analytics/tracking/1")
    ck("AC-13 stub tracking sigue igual (budget_name='')",
       r is not None and r.status_code == 200 and r.json().get("budget_name") == "")


def e1_e2_errors():
    section("E-1 / E-2 - validaciones del endpoint")
    r = api("GET", f"{PNL_URL}?date_from=2026-02-01&date_to=2026-01-01")
    ck("E-1 date_from > date_to ⇒ 400 con detail literal",
       r is not None and r.status_code == 400 and r.json().get("detail") == E1_DETAIL)
    for name, bad in (("id_budget", state.BUD + 99999), ("id_cost_center", 999999),
                      ("id_line", 999999), ("id_reference", 999999)):
        r = api("GET", f"{PNL_URL}?date_from={DFROM}&date_to={DTO}&{name}={bad}")
        ck(f"E-2 {name} inexistente ⇒ 404",
           r is not None and r.status_code == 404,
           f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{RATES_URL}/999999")
    ck("E-9 GET tasa por id inexistente ⇒ 404", r is not None and r.status_code == 404)
    r = api("POST", f"{RATES_URL}/", json={"id_line": 999999, "rate_name": "SMK BADFK",
                                           "cogs_pct": 10, "date_from": RATE_FROM,
                                           "date_to": RATE_TO})
    ck("E-2 POST tasa con FK id_line inexistente ⇒ 404",
       r is not None and r.status_code == 404)


def ac14_auth():
    section("AC-14 - JWT obligatorio")
    r = api("GET", f"{PNL_URL}?date_from={DFROM}&date_to={DTO}", auth=False)
    ck("AC-14 GET /pnl sin token ⇒ 401/403",
       r is not None and r.status_code in (401, 403),
       f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{RATES_URL}/", auth=False)
    ck("AC-14 GET /line-cost-rate/ sin token ⇒ 401/403",
       r is not None and r.status_code in (401, 403),
       f"status={r.status_code if r is not None else '?'}")


def ac15_openapi():
    section("AC-15 - OpenAPI (I-6: swagger UI en '/', spec en /openapi.json)")
    r = api("GET", "/openapi.json", auth=False)
    if r is None or r.status_code != 200:
        ck("AC-15 /openapi.json accesible", False)
        return
    spec = r.json()
    paths = spec.get("paths", {})
    pnl_path = paths.get("/budget/analytics/pnl", {}).get("get", {})
    ck("AC-15 ruta /budget/analytics/pnl documentada", bool(pnl_path))
    ck("AC-15 tag Budget Analytics", "Budget Analytics" in pnl_path.get("tags", []))
    ref = (pnl_path.get("responses", {}).get("200", {})
           .get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", ""))
    ck("AC-15 response_model ⇒ $ref PnLResponse",
       ref.endswith("/PnLResponse"), f"ref={ref}")
    lcr = paths.get("/budget/line-cost-rate/", {})
    lcri = paths.get("/budget/line-cost-rate/{id_line_cost_rate}", {})
    ck("AC-15 las 5 rutas de tasas (GET/POST raiz + GET/PUT/DELETE id)",
       all(k in lcr for k in ("get", "post")) and all(k in lcri for k in ("get", "put", "delete")))
    ck("AC-15 tag Line Cost Rates",
       "Line Cost Rates" in lcr.get("get", {}).get("tags", []))
    schemas = spec.get("components", {}).get("schemas", {})
    ck("AC-15 schemas PnL* en components",
       all(n in schemas for n in ("PnLResponse", "PnLMeta", "PnLStatement",
                                  "PnLComparison", "PnLOpex", "PnLProfit",
                                  "OpexBreakdownItem", "CogsBudgetTraceItem")))


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("P&L Engine Smoke Tests - spec backend.02_09 v1.2")
    print("=" * 64)
    print(f"Base URL: {BASE_URL} | DB: {PG_HOST}:{PG_PORT}/{PG_DB} | User: {USERNAME}")

    try:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                                password=PG_PASSWORD, dbname=PG_DB,
                                connect_timeout=10)
    except psycopg2.Error as e:
        print(f"ERROR: no hay conexión BD en {PG_HOST}:{PG_PORT}: {e}")
        return 1
    cur = conn.cursor()

    crashed = False
    try:
        # ── fase 0: pre-clean idempotente + snapshot base ──
        section("Fase 0 - pre-clean de residuos SMK")
        clean_smk(cur, "pre-clean")
        state.counts_initial = source_counts(cur)
        print(f"  [info] snapshot inicial: {state.counts_initial}")

        if not do_login():
            raise RuntimeError("Login fallido: no se puede continuar")
        ac01(cur)
        seed_catalogs(cur)
        quarantine_conflicts(cur)
        ac02(cur)
        seed_budget(cur)
        seed_execution(cur)
        sql_exec(cur, "UPDATE budgets SET status='active' WHERE id_budget = %s", (state.BUD,))
        conn.commit()

        ac13_baseline(cur)
        ac03(cur)
        ac03b(cur)
        ac09_slice_line(cur)
        ac09b_slice_reference(cur)
        ac10_cc_filter(cur)
        acx_year_cross(cur)
        ac06_no_budget(cur)
        ac07_scenario(cur)
        ac08_rate_lifecycle(cur)
        ac04_returns(cur)
        ac11_zero_margin(cur)
        e1_e2_errors()
        ac12_readonly(cur)
        ac13_final(cur)
        ac14_auth()
        ac15_openapi()
        br21_all()
    except Exception:
        crashed = True
        print()
        traceback.print_exc()
        ck("RUN - ejecución sin excepciones no capturadas", False, "ver traceback arriba")
    finally:
        # ── fase final: restaurar cuarentenas + post-clean + verificación ──
        section("Fase final - restauración y limpieza garantizada")
        try:
            clean_smk(cur, "post-clean")
            restore_quarantined(cur)
            ck("LIMPIEZA no quedaron filas SMK",
               sql_scalar(cur, "SELECT count(*) FROM budgets WHERE budget_name LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM line_cost_rates WHERE rate_name LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM invoices WHERE invoice_number LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM lines WHERE line_name LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM brands WHERE brand_name LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM product_references WHERE reference LIKE 'SMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM cost_centers WHERE cost_center_code LIKE 'SMK%'") == 0)
            counts_final = source_counts(cur)
            ck("LIMPIEZA conteos == snapshot inicial (BD intacta)",
               counts_final == state.counts_initial,
               f"final={counts_final}")
            active_smk = sql_scalar(
                cur, "SELECT count(*) FROM budgets WHERE budget_name LIKE 'SMK%' AND status='active'")
            ck("LIMPIEZA ningún presupuesto SMK activo al terminar", (active_smk or 0) == 0)
        except Exception:
            traceback.print_exc()
            ck("LIMPIEZA post-clean sin errores", False)
        cur.close()
        conn.close()

    print()
    print("=" * 64)
    print(f"RESULTS: {state.passed}/{state.total} checks OK "
          f"({state.failed} fallidos){' *CRASH* ' if crashed else ''}")
    if state.failed:
        print("Fallas:")
        for name, ok, detail in state.results:
            if not ok:
                print(f"  ✗ {name}{': ' + detail if detail else ''}")
    print("=" * 64)
    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
