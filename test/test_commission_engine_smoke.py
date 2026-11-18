"""
Commission Engine (Pilar 3) Smoke Tests - spec backend.02_11 v1.0

Verificacion runtime de AC-1..AC-16 (+ E-CM-1..5 y E-CR-1/2) contra el golden
seed deterministico de §11, con marcador "CMK" para idempotencia (pre-clean /
post-clean garantizados con try/finally). Arquitectura clon de los smokes
02_09/02_10: login JWT, seed SQL directo (MAX+1 con cadena FK completa), tasas
via POST API, cuarentena de tasas ajenas con restore en finally, reporte N/M.

Ventana golden period=2026-09 => [2026-08-26, 2026-09-25]. Verificado
2026-09-07 contra la BD dev: cero filas CASH-in reales en esa ventana (el
maximo real es 2026-03-31), asi que el golden §6.1.1 es reproducible EXACTO
sin cuarentena del ledger.

Errata de spec documentada (fila 8 de §6.1.2): la tabla dice 640.000 para el
modo "sin tasa global", pero su propio detalle ("CMK3/CMK4 pasan a pct 0.0")
implica 740.000 - 100.000 - 20.000 = 620.000 segun BR-45/48; se aserciona
620.000 junto con pct==0.0 de ambas filas y el warning agrupado.

Cobertura:
  - AC-1   tabla por create_all + rutas (analitica con $ref CommissionResponse
           y 5 rutas del CRUD) + schemas Commission* + import contenedor
  - AC-2   golden §6.1.1 exacto (3 bloques, summary, 5 renglones, rate_details,
           meta completa) + determinismo doble llamada byte-identica
  - AC-3   D-1: CMK1 11.9M -> base 10M -> 300k; tax_rate_used == 0.19; SQL
           cruzada ±0.01 de cada escalar golden
  - AC-4   D-2: CMK3 via trip->customer (S2); CMK4 anticipo sin factura (S3);
           CMK12 factura sin pedido + id_customer del ledger (period=2026-10)
  - AC-5   D-6: CMK2 sembrada -2.380.000 => +2.380.000 / +60.000
  - AC-6   BR-41: CMK6 (out) y CMK7 (NON_CASH) excluidos
  - AC-7   BR-44: CMK5 divulgada (500.000, count 1, warning literal)
  - AC-8   D-5/BR-53: bordes inclusivos, fechas explicitas == JSON (salvo
           business_period/period_source/filters), derivaciones 2026-02,
           2026-01 (cruce de ano), serie vacia valida, prelacion + warning
  - AC-9   BR-54: id_seller=S1 (620k + divulgacion global), id_line=L1 (540k,
           CMK9 echo 7.14M/6M + warning de corte), id_line=L2 (80k)
  - AC-10  BR-45/A-11: PUT global false => 620k + warning agrupado + restore;
           doble tasa L1 via SQL => gana menor id + warning de desempate
  - AC-11  BR-48: triple cuadre (Σtramos==Σrenglones==Σbloques==summary) en
           TODA respuesta capturada + Σ collected == total_collected_base
  - AC-12  BR-49: conteos identicos antes/despues de 5 llamadas en las 7
           tablas leidas + commission_rates
  - AC-13  CRUD: POST 200, solape 400 E-CR-2, pct 101 => 422, invertida 400
           E-CR-1, FK Line 404, PUT merge parcial, PUT is_active=false saca de
           resolucion, DELETE fisico + GET 404, filtros de lista
  - AC-14  regresion in-bateria: pnl / cash-flow / cash-flow-projection
           byte-a-byte (baseline post-seed); los smokes 02_09/02_10 se corren
           aparte como guardia cruzada final (no se sub-invocan aqui)
  - AC-15  errores: E-CM-1 ambos literales, E-CM-2 404s, E-CM-3 422 period,
           E-CM-4 401/403 sin token (analitica y CRUD)
  - AC-16  idempotencia (finally): cero filas CMK%, cuarentenas restauradas,
           conteos == snapshot inicial

Uso:
    1. docker compose -f docker-compose-dev.yaml up -d
    2. copiar/completar .env_test (USERNAME/PASSWORD)
    3. python test/test_commission_engine_smoke.py     (desde crm_backend/)
    4. guardia cruzada AC-14: python test/test_pnl_engine_smoke.py (208/208)
       y python test/test_cash_flow_engine_smoke.py (177/177). Los tres
       comparten budgetEngine.py y se ejecutan SECUENCIALES: cada smoke limpia
       su seed en su finally (las filas CMK de 2026-09 solo viven durante
       esta battery).
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

MARK = "CMK"                       # marcador de idempotencia
CMK_URL = "/budget/analytics/commissions"
CR_URL = "/budget/commission-rates"
GOLD_PERIOD = "2026-09"
GOLD_FROM, GOLD_TO = "2026-08-26", "2026-09-25"      # ventana derivada (D-5)
RATE_FROM, RATE_TO = "2026-01-01", "2026-12-31"
DOC_S1, DOC_S2, DOC_S3 = 9900001, 9900002, 9900003   # users.document unicos
DOC_C2, DOC_C3 = 9900022, 9900033                    # customers.document unicos
TAX = 0.19
TOL = 1e-6

INV_NUMS = ("FVFE9001", "FVFE9002", "FVFE9003", "FVFE9004")

E_CR_1_DETAIL = "date_to must be on or after date_from"
E_CR_2_DETAIL = ("Overlapping active rate for this line (or global) period; "
                 "deactivate or adjust dates first")
E_CM_1_DETAIL = "period or both date_from and date_to are required"
E_CM_1B_DETAIL = "date_from must be on or before date_to"
E_CM_3_DETAIL = "period must be YYYY-MM"
PRELATION_WARNING = "period and explicit dates both given; period wins"
UNATTR_WARNING = ("1 unattributed collection(s) totaling 500000.00 "
                  "excluded from the settlement")

# golden scalars §6.1.1
G_COLLECTED, G_NET, G_COMMISSIONS = 33320000.0, 28000000.0, 740000.0
G_UNATTR_GROSS, G_UNATTR_COUNT = 500000.0, 1

PNL_URL = "/budget/analytics/pnl"
CF_URL = "/budget/analytics/cash-flow"
PROJ_URL = "/budget/analytics/cash-flow-projection"
CF_PARAMS = (f"date_from={GOLD_FROM}&date_to={GOLD_TO}&granularity=monthly"
             f"&initial_balance=10000000&cutoff_date={GOLD_TO}")

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
        # ids del seed (dinamicos, MAX+1)
        self.S1 = self.S2 = self.S3 = None
        self.L1 = self.L2 = None
        self.BRANDA = self.BRANDB = self.REFA = self.REFB = None
        self.C2 = self.C3 = None
        self.TRP1 = self.TRP2 = None
        self.ORD1 = self.ORD2 = self.ORD3 = None
        self.INV = {}             # invoice_number -> id_invoice
        self.LEDGER = {}          # receipt_number -> id_payment_ledger
        self.RATE_L1 = self.RATE_L2 = self.RATE_GLOB = None
        # payloads capturados para AC-11
        self.payloads = {}
        # regresion AC-14 (baselines post-seed)
        self.regress = {}
        # cuarentenas de tasas ajenas (restore en finally)
        self.quarantined_rate_ids = []
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
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) \
        and not isinstance(a, bool) and abs(a - b) <= tol


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


def cm_get(query: str, tag: str):
    """GET /commissions?{query} y captura del payload para AC-11. None si fallo."""
    r = api("GET", f"{CMK_URL}?{query}")
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "sin conexion"
        body = r.text[:200] if r is not None else ""
        ck(tag, False, f"HTTP {code} {body}")
        return None
    data = r.json()
    state.payloads[tag] = data
    return data


def xsql_check(cur, tag, query, expected, params=None):
    """Verificacion SQL cruzada §12.2: el escalar golden contra su fuente."""
    got = sql_scalar(cur, query, params)
    return ck(tag, got is not None and feq(float(got), expected, tol=0.01),
              f"SQL={got} golden={expected}")


def seller_block(data, sid):
    for b in data.get("commissions_by_seller", []):
        if b["id_seller"] == sid:
            return b
    return None


def detail_row(data, receipt):
    for b in data.get("commissions_by_seller", []):
        for d in b["details"]:
            if d["receipt_number"] == receipt:
                return d
    return None


def receipts_in(data):
    return {d["receipt_number"] for b in data.get("commissions_by_seller", [])
            for d in b["details"]}


def rate_post(body):
    return api("POST", f"{CR_URL}/", json=body)


def rate_put(rid, body):
    return api("PUT", f"{CR_URL}/{rid}", json=body)


# ══════════════════════════════════════════════════════════════
# FASE 0: LIMPIEZA IDEMPOTENTE (marcador CMK)
# ══════════════════════════════════════════════════════════════

INV_IN = "(" + ",".join(f"'{n}'" for n in INV_NUMS) + ")"

# OJO triggers de la BD dev (verificados en vivo):
#   after_insert_customer      -> add_rating_default()   (hijos en ratings)
#   after_insert_customer_trip -> add_activities_from_customer_trip()
#   pedidos semilla se borran DESPUES de sus facturas (invoices.id_order es
#   FK que apunta a orders) y ANTES que trips/users; tras borrar facturas se
#   identifican por los trips CMK o por la fingerprint exacta del seed + el
#   seller/trip sembrados (no colisiona con los 197 pedidos reales de SIIGO).
CLEAN_ORDER = [
    ("payment_ledger", "DELETE FROM payment_ledger WHERE receipt_number LIKE 'CMK%'"),
    ("invoice_details",
     f"DELETE FROM invoice_details WHERE id_invoice IN "
     f"(SELECT id_invoice FROM invoices WHERE invoice_number IN {INV_IN})"),
    ("invoices", f"DELETE FROM invoices WHERE invoice_number IN {INV_IN}"),
    ("orders (seed: via trips CMK o fingerprint + seller/trip semilla)",
     f"DELETE FROM orders WHERE id_customer_trip IN "
     f"(SELECT id_customer_trip FROM customer_trips WHERE id_customer IN "
     f"(SELECT id_customer FROM customers WHERE company_name LIKE 'CMK%')) "
     f"OR ((date_order = '2026-08-01' AND delivery_date = '2026-08-15' "
     f"AND total_quantities = 1 AND total_without_tax = 10000000 "
     f"AND total_with_tax = 11900000) AND (id_seller IN "
     f"(SELECT id_user FROM users WHERE document IN ({DOC_S1},{DOC_S2},{DOC_S3})) "
     f"OR id_customer_trip IN (SELECT id_customer_trip FROM customer_trips "
     f"WHERE id_customer IN (SELECT id_customer FROM customers "
     f"WHERE company_name LIKE 'CMK%'))))"),
    ("activities (trigger del trip)",
     "DELETE FROM activities WHERE id_customer_trip IN "
     "(SELECT id_customer_trip FROM customer_trips WHERE id_customer IN "
     "(SELECT id_customer FROM customers WHERE company_name LIKE 'CMK%'))"),
    ("customer_trips",
     "DELETE FROM customer_trips WHERE id_customer IN "
     "(SELECT id_customer FROM customers WHERE company_name LIKE 'CMK%')"),
    ("ratings (trigger del customer)",
     "DELETE FROM ratings WHERE id_customer IN "
     "(SELECT id_customer FROM customers WHERE company_name LIKE 'CMK%')"),
    ("customers", "DELETE FROM customers WHERE company_name LIKE 'CMK%'"),
    ("commission_rates", "DELETE FROM commission_rates WHERE rate_name LIKE 'CMK%'"),
    ("users", f"DELETE FROM users WHERE document IN ({DOC_S1},{DOC_S2},{DOC_S3})"),
    ("product_references", "DELETE FROM product_references WHERE reference LIKE 'CMK%'"),
    ("brands", "DELETE FROM brands WHERE brand_name LIKE 'CMK%'"),
    ("lines", "DELETE FROM lines WHERE line_name LIKE 'CMK%'"),
]

COUNT_TABLES = [
    "payment_ledger", "invoices", "invoice_details", "orders",
    "customer_trips", "customers", "users", "commission_rates",
    "lines", "brands", "product_references",
]


def source_counts(cur):
    out = {}
    for t in COUNT_TABLES:
        out[t] = sql_scalar(cur, f"SELECT count(*) FROM {t}")
    return out


def clean_cmk(cur, phase):
    """Post/pre-clean idempotente. Un commit por sentencia: si una borra-
    cion falla no se pierden las ya ejecutadas (leccion piloto SMK/CFK)."""
    for table, stmt in CLEAN_ORDER:
        try:
            sql_exec(cur, stmt)
            cur.connection.commit()
        except psycopg2.Error as e:
            cur.connection.rollback()
            print(f"  [warn] {phase}: fallo limpiando {table}: "
                  f"{str(getattr(e, 'orig', e)).splitlines()[0][:120]}")


# ══════════════════════════════════════════════════════════════
# CUARENTENA DE CONFLICTOS (tasas activas ajenas que solapen la battery)
# ══════════════════════════════════════════════════════════════

def quarantine_conflicts(cur):
    """Tabla nueva => se espera 0 filas ajenas, pero por higiene (spec §11)
    desactiva toda tasa activa no-CMK que solape 2025-12-26..2026-12-31 y la
    restaura en el finally."""
    cur.execute(
        "SELECT id_commission_rate FROM commission_rates "
        "WHERE is_active AND rate_name NOT LIKE 'CMK%' "
        "AND date_from <= '2026-12-31' AND date_to >= '2025-12-26'")
    state.quarantined_rate_ids = [r[0] for r in cur.fetchall()]
    for rid in state.quarantined_rate_ids:
        sql_exec(cur, "UPDATE commission_rates SET is_active = FALSE "
                      "WHERE id_commission_rate = %s", (rid,))
    cur.connection.commit()
    if state.quarantined_rate_ids:
        print(f"  [info] cuarentena: {len(state.quarantined_rate_ids)} tasas "
              f"ajenas vigentes (se restauran al final)")


def restore_quarantined(cur):
    for rid in state.quarantined_rate_ids:
        try:
            sql_exec(cur, "UPDATE commission_rates SET is_active = TRUE "
                          "WHERE id_commission_rate = %s", (rid,))
        except psycopg2.Error:
            cur.connection.rollback()
    cur.connection.commit()
    if state.quarantined_rate_ids:
        still = sql_scalar(
            cur, "SELECT count(*) FROM commission_rates "
                 "WHERE id_commission_rate = ANY(%s) AND NOT is_active",
            (state.quarantined_rate_ids,))
        if still:
            print(f"  [warn] {still} tasa(s) en cuarentena no quedo activa tras restore")


# ══════════════════════════════════════════════════════════════
# SEED GOLDEN §11 (SQL directo MAX+1; tasas via API)
# ══════════════════════════════════════════════════════════════
#
# IMPORTANTE: leccion de secuencias del ETL/02_09 — esta BD dev tiene
# secuencias desincronizadas (nextval apunta a ids ya usados); el seed usa
# MAX+1 explicito en las 11 tablas, tecnica del propio ETL.

def next_id(cur, table, pk):
    return int(sql_scalar(cur, f"SELECT coalesce(max({pk}), 0) + 1 FROM {table}"))


def seed_users(cur):
    """3 vendedores ANA ROJO / BETO AZUL / CINDA VERDE, documentos 990000x."""
    role = sql_scalar(cur, "SELECT min(id_role) FROM roles") or 1
    for attr, first, last, doc in (
            ("S1", "ANA", "ROJO", DOC_S1), ("S2", "BETO", "AZUL", DOC_S2),
            ("S3", "CINDA", "VERDE", DOC_S3)):
        uid = next_id(cur, "users", "id_user")
        # users.password es UNIQUE en este esquema: placeholder unico por user
        sql_exec(cur,
            "INSERT INTO users (id_user, username, password, first_name, last_name, "
            "document, gender, id_role, email, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'U', %s, %s, TRUE)",
            (uid, f"cmk.{first.lower()}@smoke.test", f"no-login-{doc}", first, last,
             doc, role, f"cmk.{first.lower()}@smoke.test"))
        setattr(state, attr, uid)
    cur.connection.commit()


def seed_catalogs(cur):
    """CMK-LineA/CMK-LineB con su brand + reference (mapeo Q4 de la prorrata)."""
    lid = next_id(cur, "lines", "id_line")
    sql_exec(cur, "INSERT INTO lines (id_line, line_name) VALUES (%s, 'CMK-LineA')", (lid,))
    state.L1 = lid
    lid = next_id(cur, "lines", "id_line")
    sql_exec(cur, "INSERT INTO lines (id_line, line_name) VALUES (%s, 'CMK-LineB')", (lid,))
    state.L2 = lid
    bid = next_id(cur, "brands", "id_brand")
    sql_exec(cur, "INSERT INTO brands (id_brand, brand_name, id_line) "
                  "VALUES (%s, 'CMK-BRAND-A', %s)", (bid, state.L1))
    state.BRANDA = bid
    bid = next_id(cur, "brands", "id_brand")
    sql_exec(cur, "INSERT INTO brands (id_brand, brand_name, id_line) "
                  "VALUES (%s, 'CMK-BRAND-B', %s)", (bid, state.L2))
    state.BRANDB = bid
    # product_references NOT NULL: reference, id_brand, gender (label 'U'), value_base
    rid = next_id(cur, "product_references", "id_reference")
    sql_exec(cur, "INSERT INTO product_references (id_reference, reference, id_brand, "
                  "gender, value_base) VALUES (%s, 'CMK-REF-A1', %s, 'U', 100000)",
             (rid, state.BRANDA))
    state.REFA = rid
    rid = next_id(cur, "product_references", "id_reference")
    sql_exec(cur, "INSERT INTO product_references (id_reference, reference, id_brand, "
                  "gender, value_base) VALUES (%s, 'CMK-REF-B1', %s, 'U', 100000)",
             (rid, state.BRANDB))
    state.REFB = rid
    cur.connection.commit()


def seed_customers_orders(cur):
    """CMK-C2 (vendedor S2) / CMK-C3 (vendedor S3), trips y pedidos de la
    cadena D-2: ORD1 trae id_seller S1 (el trip -> CMK-C3 NO se usa: parada
    al primer hit); ORD2 va SIN id_seller con trip -> CMK-C2 (paso 2);
    ORD3 trae id_seller S1."""
    cid = next_id(cur, "customers", "id_customer")
    sql_exec(cur, "INSERT INTO customers (id_customer, company_name, document, address, "
                  "id_seller) VALUES (%s, 'CMK-C2', %s, '', %s)", (cid, DOC_C2, state.S2))
    state.C2 = cid
    cid = next_id(cur, "customers", "id_customer")
    sql_exec(cur, "INSERT INTO customers (id_customer, company_name, document, address, "
                  "id_seller) VALUES (%s, 'CMK-C3', %s, '', %s)", (cid, DOC_C3, state.S3))
    state.C3 = cid
    tid = next_id(cur, "customer_trips", "id_customer_trip")
    sql_exec(cur, "INSERT INTO customer_trips (id_customer_trip, id_customer, budget, "
                  "budget_quantities, with_budget) VALUES (%s, %s, 0, 0, FALSE)",
             (tid, state.C3))
    state.TRP1 = tid
    tid = next_id(cur, "customer_trips", "id_customer_trip")
    sql_exec(cur, "INSERT INTO customer_trips (id_customer_trip, id_customer, budget, "
                  "budget_quantities, with_budget) VALUES (%s, %s, 0, 0, FALSE)",
             (tid, state.C2))
    state.TRP2 = tid
    # orders NOT NULL: date_order, total_quantities, total_without_tax,
    # total_with_tax, delivery_date
    for attr, trip, seller in (("ORD1", state.TRP1, state.S1),
                               ("ORD2", state.TRP2, None),
                               ("ORD3", None, state.S1)):
        oid = next_id(cur, "orders", "id_order")
        sql_exec(cur, "INSERT INTO orders (id_order, id_customer_trip, id_seller, "
                      "date_order, total_quantities, total_without_tax, "
                      "total_with_tax, delivery_date) "
                      "VALUES (%s, %s, %s, '2026-08-01', 1, 10000000, 11900000, "
                      "'2026-08-15')", (oid, trip, seller))
        setattr(state, attr, oid)
    cur.connection.commit()


def insert_invoice(cur, num, id_order):
    iid = next_id(cur, "invoices", "id_invoice")
    sql_exec(cur, "INSERT INTO invoices (id_invoice, invoice_number, key, invoice_date, "
                  "id_order, total_quantities, total_without_tax, total_discount, "
                  "total_with_tax) VALUES (%s, %s, 1, '2026-08-01', %s, 1, "
                  "10000000, 0, 11900000)", (iid, num, id_order))
    state.INV[num] = iid
    return iid


def insert_detail(cur, iid, ref, brand, value):
    did = next_id(cur, "invoice_details", "id_invoice_detail")
    sql_exec(cur,
        "INSERT INTO invoice_details (id_invoice_detail, id_invoice, id_reference, "
        "product, description, color, size, id_brand, gender, unit_value, quantity, "
        "value_without_tax, discount, value_with_tax) "
        "VALUES (%s, %s, %s, 'CMK', 'CMK detail', 'U', 'U', %s, 'U', %s, 1, %s, 0, %s)",
        (did, iid, ref, brand, value, value, value * 1.19))


def seed_invoices(cur):
    """FVFE9001: pedido S1, detalle 100 % LineA (10M netos).
    FVFE9002: pedido SIN id_seller (trip -> CMK-C2), CERO detalles -> global.
    FVFE9003: pedido S1, detalles LineA 6M / LineB 4M -> prorrata 60/40.
    FVFE9004: SIN pedido (cadena rota -> paso 3 con factura presente, AC-4)."""
    iid = insert_invoice(cur, "FVFE9001", state.ORD1)
    insert_detail(cur, iid, state.REFA, state.BRANDA, 10000000)
    insert_invoice(cur, "FVFE9002", state.ORD2)
    iid = insert_invoice(cur, "FVFE9003", state.ORD3)
    insert_detail(cur, iid, state.REFA, state.BRANDA, 6000000)
    insert_detail(cur, iid, state.REFB, state.BRANDB, 4000000)
    insert_invoice(cur, "FVFE9004", None)
    cur.connection.commit()


def seed_ledger(cur):
    """12 recibos CMK1..CMK12 segun trazas §6.1.1 + §11. La ventana golden
    [2026-08-26, 2026-09-25] recoge CMK1/2/3/4/9; CMK5 no-atribuible (BR-44);
    CMK6 'out' y CMK7 NON_CASH fuera del gatillo (BR-41); CMK8 (07-31),
    CMK10 (08-25) y CMK11 (09-26) fuera de ventana (bordes D-5); CMK12 cae
    en la ventana 2026-10 con factura sin pedido + id_customer del ledger."""
    # (receipt, nature, flow, date, amount, invoice_number, customer attr)
    rows = [
        ("CMK1",  "CASH", "in",  "2026-08-26", 11900000, "FVFE9001", None),
        ("CMK2",  "CASH", "in",  "2026-09-10", -2380000, "FVFE9001", None),   # D-6
        ("CMK3",  "CASH", "in",  "2026-09-25",  5950000, "FVFE9002", None),
        ("CMK4",  "CASH", "in",  "2026-09-01",  1190000, None, "C3"),         # anticipo
        ("CMK5",  "CASH", "in",  "2026-09-05",   500000, None, None),         # BR-44
        ("CMK6",  "CASH", "out", "2026-09-02",  1190000, "FVFE9001", None),   # BR-41
        ("CMK7",  "NON_CASH_ADJUSTMENT", None, "2026-09-03", 9999999, None, None),
        ("CMK8",  "CASH", "in",  "2026-07-31",  1190000, "FVFE9001", None),   # fuera
        ("CMK9",  "CASH", "in",  "2026-09-15", 11900000, "FVFE9003", None),   # D-7
        ("CMK10", "CASH", "in",  "2026-08-25",  1190000, "FVFE9001", None),   # borde -1
        ("CMK11", "CASH", "in",  "2026-09-26",  1190000, "FVFE9001", None),   # borde +1
        ("CMK12", "CASH", "in",  "2026-10-05",  2380000, "FVFE9004", "C2"),   # AC-4
    ]
    for receipt, nature, flow, pdate, amount, inv, cust in rows:
        pid = next_id(cur, "payment_ledger", "id_payment_ledger")
        sql_exec(cur,
            "INSERT INTO payment_ledger (id_payment_ledger, receipt_number, "
            "transaction_nature, cash_flow, payment_date, payment_amount, "
            "accounting_account, description, id_invoice, id_customer) "
            "VALUES (%s, %s, %s, %s, %s, %s, '', 'CMK', %s, %s)",
            (pid, receipt, nature, flow, pdate, amount,
             state.INV.get(inv) if inv else None,
             getattr(state, cust) if cust else None))
        state.LEDGER[receipt] = pid
    cur.connection.commit()


def seed_rates_via_api():
    """D-3: las tasas se crean por el API POST /budget/commission-rates.
    Orden L1 3%, L2 2%, global 2% (ids crecientes: 51/52/53 ilustrativos)."""
    r = rate_post({"id_line": state.L1, "rate_name": "CMK L1 2026",
                   "commission_pct": 3.00, "date_from": RATE_FROM, "date_to": RATE_TO})
    ok = r is not None and r.status_code == 200
    ck("seed POST L1 3% ⇒ 200", ok,
       r.text[:120] if r is not None else "sin conexion")
    if ok:
        state.RATE_L1 = r.json()["id_commission_rate"]
    r = rate_post({"id_line": state.L2, "rate_name": "CMK L2 2026",
                   "commission_pct": 2.00, "date_from": RATE_FROM, "date_to": RATE_TO})
    ok = r is not None and r.status_code == 200
    ck("seed POST L2 2% ⇒ 200", ok)
    if ok:
        state.RATE_L2 = r.json()["id_commission_rate"]
    r = rate_post({"id_line": None, "rate_name": "CMK GLOBAL 2026",
                   "commission_pct": 2.00, "date_from": RATE_FROM, "date_to": RATE_TO})
    ok = r is not None and r.status_code == 200
    ck("seed POST global 2% ⇒ 200", ok)
    if ok:
        state.RATE_GLOB = r.json()["id_commission_rate"]
    return all(v is not None for v in (state.RATE_L1, state.RATE_L2, state.RATE_GLOB))


# ══════════════════════════════════════════════════════════════
# AC-11/BR-48: invariantes de soporte de pago sobre TODA respuesta
# ══════════════════════════════════════════════════════════════

def br48_all():
    section("AC-11 - invariante BR-48 en todas las respuestas capturadas")
    for tag, data in state.payloads.items():
        s = data["summary"]
        rows = [d for b in data["commissions_by_seller"] for d in b["details"]]
        sum_blocks = round(sum(b["total_commission"] for b in
                               data["commissions_by_seller"]), 2)
        sum_rows = round(sum(d["commission_earned"] for d in rows), 2)
        sum_traces = round(sum(t["commission_earned"] for d in rows
                               for t in d["rate_details"]), 2)
        ck(f"{tag}:BR48 Σvendedores==Σrenglones==Σtramos==total",
           feq(sum_blocks, s["total_commissions_calculated"])
           and feq(sum_rows, s["total_commissions_calculated"])
           and feq(sum_traces, s["total_commissions_calculated"]),
           f"blocks={sum_blocks} rows={sum_rows} traces={sum_traces} "
           f"summary={s['total_commissions_calculated']}")
        sum_collected = round(sum(d["collected_amount"] for d in rows), 2)
        ck(f"{tag}:BR48 Σcollected==total_collected_base",
           feq(sum_collected, s["total_collected_base"]),
           f"Σ={sum_collected} summary={s['total_collected_base']}")
        sum_net = round(sum(d["commission_base"] for d in rows), 2)
        ck(f"{tag}:BR48 Σbase==total_net_base",
           feq(sum_net, s["total_net_base"]),
           f"Σ={sum_net} summary={s['total_net_base']}")
        for d in rows:
            ck(f"{tag}:{d['receipt_number']}:row==Σtramos",
               feq(d["commission_earned"],
                   round(sum(t["commission_earned"] for t in d["rate_details"]), 2)))
            ck(f"{tag}:{d['receipt_number']}:collected>=0 (D-6)",
               d["collected_amount"] >= 0)
            ck(f"{tag}:{d['receipt_number']}:base==collected/1.19 (D-1)",
               feq(d["commission_base"],
                   round(d["collected_amount"] / (1 + TAX), 2), tol=0.02))


# ══════════════════════════════════════════════════════════════
# PRUEBAS AC-1 .. AC-16
# ══════════════════════════════════════════════════════════════

def do_login():
    section("Login (POST /login/)")
    r = api("POST", "/login/", auth=False,
            json={"username": USERNAME, "password": PASSWORD})
    if r is not None and r.status_code == 200:
        state.token = r.json().get("access_token")
        state.headers = {"Authorization": f"Bearer {state.token}"}
        ck("Login JWT", bool(state.token))
        return True
    ck("Login JWT", False, f"status={r.status_code if r is not None else 'sin conexion'}")
    return False


def ac01(cur):
    section("AC-1 - integracion/DDL (tabla, import, OpenAPI)")
    reg = sql_scalar(cur, "SELECT to_regclass('public.commission_rates')::text")
    ck("AC-1 tabla commission_rates existe (create_all)",
       reg == "commission_rates", f"to_regclass={reg}")
    cols = [r[0] for r in
            (cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'commission_rates' ORDER BY ordinal_position"),
             cur.fetchall())[1]]
    ck("AC-1 columnas clon exacto de line_cost_rates (cogs_pct->commission_pct)",
       set(cols) == {"id_commission_rate", "id_line", "rate_name", "commission_pct",
                     "date_from", "date_to", "is_active", "created_at", "updated_at"},
       f"cols={cols}")
    try:
        p = subprocess.run(
            ["docker", "exec", "crm_backend_dev", "python", "-c",
             "from app.schemas import CommissionResponse, CommissionRate; "
             "print('IMPORT_OK')"],
            capture_output=True, text=True, timeout=120)
        ck("AC-1 from app.schemas import CommissionResponse (en contenedor)",
           "IMPORT_OK" in p.stdout, (p.stderr or p.stdout)[:120])
    except FileNotFoundError:
        ck("AC-1 import de schemas (docker CLI no disponible)", False,
           "docker no está en el PATH del host")
    r = api("GET", "/openapi.json", auth=False)
    if r is None or r.status_code != 200:
        ck("AC-1 /openapi.json accesible", False)
        return
    spec = r.json()
    paths = spec.get("paths", {})
    cpath = paths.get("/budget/analytics/commissions", {}).get("get", {})
    ck("AC-1 ruta GET /budget/analytics/commissions documentada", bool(cpath))
    ck("AC-1 tag Budget Analytics", "Budget Analytics" in cpath.get("tags", []))
    ref = (cpath.get("responses", {}).get("200", {})
           .get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", ""))
    ck("AC-1 response_model ⇒ $ref CommissionResponse",
       ref.endswith("/CommissionResponse"), f"ref={ref}")
    qnames = [q.get("name") for q in cpath.get("parameters", [])]
    ck("AC-1 los 5 query params presentes",
       all(k in qnames for k in ("period", "date_from", "date_to", "id_seller",
                                 "id_line")), f"got={qnames}")
    cr_root = paths.get("/budget/commission-rates/", {})
    cr_id = paths.get("/budget/commission-rates/{id_commission_rate}", {})
    ck("AC-1 las 5 rutas del CRUD (GET/POST raiz + GET/PUT/DELETE id)",
       all(k in cr_root for k in ("get", "post"))
       and all(k in cr_id for k in ("get", "put", "delete")))
    ck("AC-1 tag Commission Rates",
       "Commission Rates" in cr_root.get("get", {}).get("tags", []))
    schemas = spec.get("components", {}).get("schemas", {})
    ck("AC-1 schemas Commission* en components",
       all(n in schemas for n in ("CommissionRate", "CommissionRateCreate",
                                  "CommissionRateUpdate", "CommissionRateTrace",
                                  "CommissionDetailRow", "CommissionSellerBlock",
                                  "CommissionSummary", "CommissionMeta",
                                  "CommissionResponse")))
    ck("AC-1 sin colision: line-cost-rate sigue montada",
       "/budget/line-cost-rate/" in paths)


def ac02(cur):
    section("AC-2 - golden §6.1.1 exacto (period=2026-09)")
    data = cm_get(f"period={GOLD_PERIOD}", "AC-2")
    if data is None:
        return
    ck("AC-2 ventana derivada echo [26-ago, 25-sep] (D-5)",
       data["period"] == {"from": GOLD_FROM, "to": GOLD_TO}, f"got={data['period']}")
    ck_keys("AC-2 summary", data["summary"],
            {"total_collected_base": G_COLLECTED, "total_net_base": G_NET,
             "total_commissions_calculated": G_COMMISSIONS,
             "total_unattributed_collected": G_UNATTR_GROSS,
             "unattributed_count": G_UNATTR_COUNT})
    blocks = data["commissions_by_seller"]
    ck("AC-2 3 bloques ordenados por id_seller ASC (BR-52)",
       [b["id_seller"] for b in blocks] == [state.S1, state.S2, state.S3],
       f"got={[b['id_seller'] for b in blocks]}")
    if len(blocks) != 3:
        return
    b1, b2, b3 = blocks
    ck_keys("AC-2 bloque S1", b1,
            {"id_seller": state.S1, "seller_name": "ANA ROJO",
             "total_collected": 26180000.0, "total_commission": 620000.0})
    ck("AC-2 S1 detalles en orden Q1 CMK1,CMK2,CMK9 (BR-52)",
       [d["receipt_number"] for d in b1["details"]] == ["CMK1", "CMK2", "CMK9"],
       f"got={[d['receipt_number'] for d in b1['details']]}")
    ck_keys("AC-2 bloque S2", b2,
            {"id_seller": state.S2, "seller_name": "BETO AZUL",
             "total_collected": 5950000.0, "total_commission": 100000.0})
    ck_keys("AC-2 bloque S3", b3,
            {"id_seller": state.S3, "seller_name": "CINDA VERDE",
             "total_collected": 1190000.0, "total_commission": 20000.0})

    if len(b1["details"]) == 3:
        d1, d2, d9 = b1["details"]
        ck_keys("AC-2 CMK1 row", d1,
                {"id_payment_ledger": state.LEDGER["CMK1"], "receipt_number": "CMK1",
                 "payment_date": "2026-08-26", "invoice_number": "FVFE9001",
                 "collected_amount": 11900000.0, "commission_base": 10000000.0,
                 "commission_rate_applied": 3.0, "commission_earned": 300000.0})
        ck_keys("AC-2 CMK1 tramo", (d1["rate_details"] or [None])[0],
                {"id_commission_rate": state.RATE_L1, "id_line": state.L1,
                 "line_name": "CMK-LineA", "commission_pct": 3.0,
                 "base_net": 10000000.0, "commission_earned": 300000.0})
        ck_keys("AC-2 CMK2 row", d2,
                {"id_payment_ledger": state.LEDGER["CMK2"], "receipt_number": "CMK2",
                 "payment_date": "2026-09-10", "invoice_number": "FVFE9001",
                 "collected_amount": 2380000.0, "commission_base": 2000000.0,
                 "commission_rate_applied": 3.0, "commission_earned": 60000.0})
        ck_keys("AC-2 CMK9 row", d9,
                {"id_payment_ledger": state.LEDGER["CMK9"], "receipt_number": "CMK9",
                 "payment_date": "2026-09-15", "invoice_number": "FVFE9003",
                 "collected_amount": 11900000.0, "commission_base": 10000000.0,
                 "commission_rate_applied": 2.6, "commission_earned": 260000.0})
        tr = d9["rate_details"]
        ck("AC-2 CMK9 dos tramos 60/40 en orden de linea (BR-46/52)",
           len(tr) == 2 and tr[0]["id_line"] == state.L1 and tr[1]["id_line"] == state.L2,
           f"got={tr}")
        if len(tr) == 2:
            ck_keys("AC-2 CMK9 tramo L1", tr[0],
                    {"id_commission_rate": state.RATE_L1, "line_name": "CMK-LineA",
                     "commission_pct": 3.0, "base_net": 6000000.0,
                     "commission_earned": 180000.0})
            ck_keys("AC-2 CMK9 tramo L2", tr[1],
                    {"id_commission_rate": state.RATE_L2, "line_name": "CMK-LineB",
                     "commission_pct": 2.0, "base_net": 4000000.0,
                     "commission_earned": 80000.0})
    d3 = detail_row(data, "CMK3")
    ck_keys("AC-2 CMK3 row (S2, factura sin detalles -> global)", d3,
            {"id_payment_ledger": state.LEDGER["CMK3"], "receipt_number": "CMK3",
             "payment_date": "2026-09-25", "invoice_number": "FVFE9002",
             "collected_amount": 5950000.0, "commission_base": 5000000.0,
             "commission_rate_applied": 2.0, "commission_earned": 100000.0})
    ck_keys("AC-2 CMK3 tramo global", (d3 or {}).get("rate_details", [None])[0],
            {"id_commission_rate": state.RATE_GLOB, "id_line": None,
             "line_name": None, "commission_pct": 2.0, "base_net": 5000000.0,
             "commission_earned": 100000.0})
    d4 = detail_row(data, "CMK4")
    ck_keys("AC-2 CMK4 row (anticipo, invoice_number null)", d4,
            {"id_payment_ledger": state.LEDGER["CMK4"], "receipt_number": "CMK4",
             "payment_date": "2026-09-01", "invoice_number": None,
             "collected_amount": 1190000.0, "commission_base": 1000000.0,
             "commission_rate_applied": 2.0, "commission_earned": 20000.0})

    meta = data["meta"]
    ck_keys("AC-2 meta", meta,
            {"business_period": "2026-09", "period_source": "period_param",
             "tax_rate_used": TAX})
    ck("AC-2 meta.filters eco de los 5 params (period => fechas null, BR-52)",
       meta["filters"] == {"period": "2026-09", "date_from": None, "date_to": None,
                           "id_seller": None, "id_line": None}, f"got={meta['filters']}")
    ck("AC-2 warnings == [no-atribuibles literal]",
       meta["warnings"] == [UNATTR_WARNING], f"got={meta['warnings']}")

    # determinismo BR-52: doble llamada byte-identica
    r2 = api("GET", f"{CMK_URL}?period={GOLD_PERIOD}")
    ck("AC-2/BR-52 doble llamada byte-idéntica",
       r2 is not None and r2.status_code == 200
       and json.dumps(r2.json(), sort_keys=True) == json.dumps(data, sort_keys=True))


def ac03(cur):
    section("AC-3 - D-1 base neta de IVA + tax_rate_used + SQL cruzada")
    data = state.payloads.get("AC-2") or cm_get(f"period={GOLD_PERIOD}", "AC-3")
    if data is None:
        return
    d1 = detail_row(data, "CMK1")
    ck("AC-3 CMK1 collected 11.9M -> base EXACTA 10M (numero limpio de IVA)",
       d1 is not None and feq(d1["collected_amount"], 11900000.0)
       and feq(d1["commission_base"], 10000000.0), f"got={d1}")
    ck("AC-3 earned = 10M x 3% = 300.000",
       d1 is not None and feq(d1["commission_earned"], 300000.0))
    ck("AC-3 meta.tax_rate_used == 0.19 (constante app.core.constants)",
       data["meta"]["tax_rate_used"] == 0.19, f"got={data['meta']['tax_rate_used']}")
    # §12.2: cada escalar golden cruzado contra su propia fuente SQL
    xsql_check(cur, "AC-3 SQL× Σ bruto atribuido == total_collected_base",
               "SELECT coalesce(sum(abs(payment_amount)),0) FROM payment_ledger "
               "WHERE receipt_number IN ('CMK1','CMK2','CMK3','CMK4','CMK9') "
               "AND transaction_nature='CASH' AND cash_flow='in'", G_COLLECTED)
    xsql_check(cur, "AC-3 SQL× Σ neto /1.19 == total_net_base",
               "SELECT coalesce(sum(abs(payment_amount) / %s),0) FROM payment_ledger "
               "WHERE receipt_number IN ('CMK1','CMK2','CMK3','CMK4','CMK9') "
               "AND transaction_nature='CASH' AND cash_flow='in'", G_NET, (1 + TAX,))
    xsql_check(cur, "AC-3 SQL× L1 puro (CMK1+CMK2) x 3% == 360.000",
               "SELECT coalesce(sum(abs(payment_amount)) / %s * 0.03,0) "
               "FROM payment_ledger WHERE receipt_number IN ('CMK1','CMK2')",
               360000.0, (1 + TAX,))
    xsql_check(cur, "AC-3 SQL× L2 tramo CMK9 (4M nets x 2%) == 80.000",
               "SELECT coalesce(sum(d.value_without_tax),0) * 0.02 FROM invoice_details d "
               "JOIN product_references pr ON pr.id_reference = d.id_reference "
               "JOIN brands br ON br.id_brand = pr.id_brand "
               "WHERE br.id_line = %s AND d.id_invoice = %s",
               80000.0, (state.L2, state.INV["FVFE9003"]))
    xsql_check(cur, "AC-3 SQL× peso LineA de FVFE9003 == 60 %",
               "SELECT coalesce(sum(d.value_without_tax),0) / "
               "(SELECT sum(value_without_tax) FROM invoice_details WHERE id_invoice = %s) "
               "FROM invoice_details d JOIN product_references pr "
               "ON pr.id_reference = d.id_reference JOIN brands br "
               "ON br.id_brand = pr.id_brand "
               "WHERE d.id_invoice = %s AND br.id_line = %s",
               0.6, (state.INV["FVFE9003"], state.INV["FVFE9003"], state.L1))
    xsql_check(cur, "AC-3 SQL× global puros (CMK3+CMK4) x 2% == 120.000",
               "SELECT coalesce(sum(abs(payment_amount)) / %s * 0.02,0) "
               "FROM payment_ledger WHERE receipt_number IN ('CMK3','CMK4')",
               120000.0, (1 + TAX,))


def ac04(cur):
    section("AC-4 - D-2/BR-43 cadena de atribucion con parada al primer hit")
    data = state.payloads.get("AC-2") or cm_get(f"period={GOLD_PERIOD}", "AC-4")
    if data is None:
        return
    b2 = seller_block(data, state.S2)
    ck("AC-4 CMK3 atribuida a S2 via trip->customer (ORD2 sin id_seller, paso 2)",
       b2 is not None and any(d["receipt_number"] == "CMK3" for d in b2["details"]))
    b3 = seller_block(data, state.S3)
    ck("AC-4 CMK4 anticipo atribuido a S3 via ledger.id_customer, invoice null (paso 3)",
       b3 is not None and any(d["receipt_number"] == "CMK4"
                              and d["invoice_number"] is None for d in b3["details"]))
    b1 = seller_block(data, state.S1)
    ck("AC-4 CMK1 (ORD1 S1 con trip->CMK-C3) no cae al paso 2: parada al primer hit",
       b1 is not None and any(d["receipt_number"] == "CMK1" for d in b1["details"]))
    # CMK12: factura SIN id_order + id_customer del ledger => paso 3 con factura
    d12 = cm_get("period=2026-10", "AC-4-CMK12")
    if d12 is None:
        return
    r12 = detail_row(d12, "CMK12")
    ck("AC-4 CMK12 (period=2026-10) atribuido a S2 con invoice_number FVFE9004",
       r12 is not None and seller_block(d12, state.S2) is not None
       and r12.get("invoice_number") == "FVFE9004", f"got={r12}")
    ck_keys("AC-4 CMK12 row", r12,
            {"receipt_number": "CMK12", "payment_date": "2026-10-05",
             "collected_amount": 2380000.0, "commission_base": 2000000.0,
             "commission_rate_applied": 2.0, "commission_earned": 40000.0})
    b1x = seller_block(d12, state.S1)
    ck("AC-4/AC-8 ventana 2026-10: CMK11 (borde +1) entra con 30.000; summary limpio",
       feq(d12["summary"]["total_commissions_calculated"], 70000.0)
       and d12["summary"]["unattributed_count"] == 0
       and b1x is not None and feq(b1x["total_commission"], 30000.0),
       f"got={d12['summary']}")
    ck("AC-4 ventana 2026-10 == [2026-09-26, 2026-10-25]",
       d12["period"] == {"from": "2026-09-26", "to": "2026-10-25"},
       f"got={d12['period']}")


def ac05(cur):
    section("AC-5 - D-6/BR-42: normalizacion abs() en la fuente (dato adverso)")
    data = state.payloads.get("AC-2") or cm_get(f"period={GOLD_PERIOD}", "AC-5")
    stored = sql_scalar(cur, "SELECT payment_amount FROM payment_ledger "
                             "WHERE receipt_number = 'CMK2'")
    ck("AC-5 CMK2 almacenada como -2.380.000 (signo adverso)",
       stored is not None and feq(float(stored), -2380000.0), f"stored={stored}")
    d2 = detail_row(data, "CMK2") if data else None
    ck("AC-5 payload: collected +2.380.000 y comision +60.000 (jamas renglon negativo)",
       d2 is not None and feq(d2["collected_amount"], 2380000.0)
       and feq(d2["commission_earned"], 60000.0), f"got={d2}")
    ck("AC-5 ninguna comision ni bruto negativo en toda la liquidacion",
       data is not None and all(d["commission_earned"] >= 0
                                and d["collected_amount"] >= 0
                                for b in data["commissions_by_seller"]
                                for d in b["details"]))


def ac06(cur):
    section("AC-6 - BR-41: unico gatillo CASH-in (out/NULL/NON_CASH excluidos)")
    data = state.payloads.get("AC-2") or cm_get(f"period={GOLD_PERIOD}", "AC-6")
    ck("AC-6 CMK6 (out) y CMK7 (NON_CASH) existen en BD",
       sql_scalar(cur, "SELECT count(*) FROM payment_ledger "
                       "WHERE receipt_number IN ('CMK6','CMK7')") == 2)
    rows = receipts_in(data) if data else set()
    ck("AC-6 CMK6/CMK7 no aparecen en ningun renglon",
       "CMK6" not in rows and "CMK7" not in rows, f"got={rows}")
    ck("AC-6 los totales golden no los reflejan (740.000 exacto)",
       data is not None
       and feq(data["summary"]["total_commissions_calculated"], G_COMMISSIONS))
    ck("AC-6 membresia exacta de la ventana: CMK1,2,3,4,9",
       rows == {"CMK1", "CMK2", "CMK3", "CMK4", "CMK9"}, f"got={rows}")
    # el NON_CASH (9.999.999) no se filtra a ningun escalar
    vals = [v for b in (data or {}).get("commissions_by_seller", [])
            for d in b["details"] for v in (d["collected_amount"], d["commission_base"],
                                            d["commission_earned"])]
    ck("AC-6 9.999.999 no aparece en ningun valor del payload",
       not any(abs(v) in (9999999.0, 9999998.99, 9999999.01) for v in vals))


def ac07(cur):
    section("AC-7 - BR-44: no-atribuible excluido pero divulgado (jamasc silencioso)")
    data = state.payloads.get("AC-2") or cm_get(f"period={GOLD_PERIOD}", "AC-7")
    if data is None:
        return
    ck_keys("AC-7 summary no-atribuibles", data["summary"],
            {"total_unattributed_collected": G_UNATTR_GROSS,
             "unattributed_count": G_UNATTR_COUNT})
    ck("AC-7 warning literal con conteo y monto",
       data["meta"]["warnings"] == [UNATTR_WARNING], f"got={data['meta']['warnings']}")
    ck("AC-7 CMK5 no esta en ningun bloque de vendedor",
       detail_row(data, "CMK5") is None)
    xsql_check(cur, "AC-7 SQL× CMK5 == 500.000 (CASH in en ventana, sin cadena)",
               "SELECT coalesce(sum(abs(payment_amount)),0) FROM payment_ledger "
               "WHERE receipt_number='CMK5' AND transaction_nature='CASH' "
               "AND cash_flow='in' AND payment_date BETWEEN %s AND %s",
               G_UNATTR_GROSS, (GOLD_FROM, GOLD_TO))


def ac08(cur):
    section("AC-8 - D-5/BR-53: periodo comercial 26->25, eco y prelacion")
    gold = state.payloads.get("AC-2")
    # fechas explicitas == misma ventana == JSON identico salvo eco de meta
    data = cm_get(f"date_from={GOLD_FROM}&date_to={GOLD_TO}", "AC-8-fechas")
    if data is not None and gold is not None:
        body_g = {k: v for k, v in gold.items() if k != "meta"}
        body_d = {k: v for k, v in data.items() if k != "meta"}
        ck("AC-8 fechas explicitas: payload (fuera de meta) identico al golden",
           json.dumps(body_g, sort_keys=True) == json.dumps(body_d, sort_keys=True))
        ck_keys("AC-8 meta modo explicit_dates", data["meta"],
                {"business_period": None, "period_source": "explicit_dates"})
        ck("AC-8 filters ecoa las fechas recibidas (period null)",
           data["meta"]["filters"] == {
               "period": None, "date_from": GOLD_FROM, "date_to": GOLD_TO,
               "id_seller": None, "id_line": None}, f"got={data['meta']['filters']}")
    # bordes inclusivos del periodo golden (CMK1 08-26 dentro, CMK10 08-25 fuera,
    # CMK3 09-25 dentro, CMK11 09-26 fuera) ya probado por la membresia AC-6
    rows = receipts_in(gold) if gold else set()
    ck("AC-8 bordes: {CMK1,CMK3} dentro, {CMK8,CMK10,CMK11} fuera",
       {"CMK1", "CMK3"} <= rows and not ({"CMK8", "CMK10", "CMK11"} & rows),
       f"got={rows}")
    # derivaciones (eco; en 2026-02 SI existen recaudos reales preexistentes =>
    # solo se aserciona la ventana derivada, no la liquidacion cero)
    d2 = cm_get("period=2026-02", "AC-8-feb")
    if d2 is not None:
        ck("AC-8 period=2026-02 deriva [2026-01-26, 2026-02-25] + business_period",
           d2["period"] == {"from": "2026-01-26", "to": "2026-02-25"}
           and d2["meta"]["business_period"] == "2026-02", f"got={d2['period']}")
    d27 = cm_get("period=2027-02", "AC-8-feb27")
    if d27 is not None:
        ck("AC-8 period=2027-02 deriva [2027-01-26, 2027-02-25]",
           d27["period"] == {"from": "2027-01-26", "to": "2027-02-25"})
    d01 = cm_get("period=2026-01", "AC-8-ene")
    if d01 is not None:
        ck("AC-8 enero deriva del diciembre anterior (cruce de ano)",
           d01["period"] == {"from": "2025-12-26", "to": "2026-01-25"},
           f"got={d01['period']}")
    # serie validamente vacia: ventana 2026-05 sin recaudos (reales ni semilla)
    vacia = sql_scalar(cur, "SELECT count(*) FROM payment_ledger WHERE "
                            "transaction_nature='CASH' AND cash_flow='in' AND "
                            "payment_date BETWEEN '2026-04-26' AND '2026-05-25'")
    ck("AC-8 pre-condicion: ventana 2026-05 realmente vacia en esta BD", vacia == 0,
       f"filas_reales={vacia}")
    d5 = cm_get("period=2026-05", "AC-8-vacia")
    if d5 is not None:
        ck("AC-8 serie vacia valida (200, 0.0, sin bloques, sin warnings)",
           feq(d5["summary"]["total_commissions_calculated"], 0.0)
           and d5["commissions_by_seller"] == []
           and d5["summary"]["unattributed_count"] == 0
           and d5["meta"]["warnings"] == [], f"got={d5['summary']}")
    # period + fechas: period manda + warning literal de prelacion
    dpre = cm_get(f"period={GOLD_PERIOD}&date_from=2026-01-01&date_to=2026-12-31",
                  "AC-8-prelacion")
    if dpre is not None:
        ck("AC-8 prelacion: ventana == la del period, total 740.000",
           dpre["period"] == {"from": GOLD_FROM, "to": GOLD_TO}
           and feq(dpre["summary"]["total_commissions_calculated"], G_COMMISSIONS))
        ck("AC-8 warning de prelacion ANTES que los de datos (orden §6.1.3)",
           dpre["meta"]["warnings"] == [PRELATION_WARNING, UNATTR_WARNING],
           f"got={dpre['meta']['warnings']}")
        ck("AC-8 con prelacion business_period/period_source siguen siendo del period",
           dpre["meta"]["business_period"] == "2026-09"
           and dpre["meta"]["period_source"] == "period_param")


def ac09(cur):
    section("AC-9 - BR-54: filtros post-atribucion id_seller / id_line")
    # --- id_seller=S1: solo su bloque; divulgacion no-atribuible GLOBAL ---
    d1 = cm_get(f"period={GOLD_PERIOD}&id_seller={state.S1}", "AC-9-seller")
    if d1 is not None:
        blks = d1["commissions_by_seller"]
        ck("AC-9 id_seller=S1: exactamente 1 bloque con 620.000",
           [b["id_seller"] for b in blks] == [state.S1]
           and feq(blks[0]["total_commission"], 620000.0),
           f"got={[(b['id_seller'], b['total_commission']) for b in blks]}")
        ck_keys("AC-9 id_seller=S1 summary (26.18M; no-atribuibles globales)", d1["summary"],
                {"total_collected_base": 26180000.0,
                 "total_unattributed_collected": G_UNATTR_GROSS,
                 "unattributed_count": G_UNATTR_COUNT})
        ck("AC-9 divulgacion no-atribuible intacta bajo id_seller (BR-54)",
           d1["meta"]["warnings"] == [UNATTR_WARNING], f"got={d1['meta']['warnings']}")
        ck("AC-9 filters ecoa id_seller", d1["meta"]["filters"]["id_seller"] == state.S1)
    # --- id_line=L1: CMK9 podado a su tramo con bruto proporcional 7.14M ---
    dl1 = cm_get(f"period={GOLD_PERIOD}&id_line={state.L1}", "AC-9-L1")
    if dl1 is not None:
        ck("AC-9 id_line=L1: total 540.000",
           feq(dl1["summary"]["total_commissions_calculated"], 540000.0),
           f"got={dl1['summary']['total_commissions_calculated']}")
        d9 = detail_row(dl1, "CMK9")
        ck_keys("AC-9 CMK9 podado a L1 (base 6M, bruto echo 7.14M, tasa unica 3.0)", d9,
                {"collected_amount": 7140000.0, "commission_base": 6000000.0,
                 "commission_rate_applied": 3.0, "commission_earned": 180000.0})
        ck("AC-9 CMK9 conserva exactamente 1 tramo L1 (Σtramos==renglon, BR-46)",
           d9 is not None and len(d9["rate_details"]) == 1
           and d9["rate_details"][0]["id_line"] == state.L1)
        ck("AC-9 CMK3/CMK4 (sin linea) excluidos => sin bloques S2/S3 vacios",
           seller_block(dl1, state.S2) is None and seller_block(dl1, state.S3) is None)
        ck("AC-9 summary coherente con el corte: collected 21.42M / neto 18M",
           feq(dl1["summary"]["total_collected_base"], 21420000.0)
           and feq(dl1["summary"]["total_net_base"], 18000000.0),
           f"got={dl1['summary']}")
        w = dl1["meta"]["warnings"]
        ck("AC-9 warning de corte con conteo (2), orden tras no-atribuibles (§6.1.3)",
           len(w) == 2 and w[0] == UNATTR_WARNING
           and w[1] == (f"2 collected row(s) had no participation in line {state.L1} "
                        "and were excluded from the settlement"),
           f"got={w}")
        ck("AC-9 filters ecoa id_line", dl1["meta"]["filters"]["id_line"] == state.L1)
    # --- id_line=L2: solo el tramo de CMK9 ---
    dl2 = cm_get(f"period={GOLD_PERIOD}&id_line={state.L2}", "AC-9-L2")
    if dl2 is not None:
        ck("AC-9 id_line=L2: total 80.000 y un solo renglon (CMK9 echo 4.76M)",
           feq(dl2["summary"]["total_commissions_calculated"], 80000.0)
           and receipts_in(dl2) == {"CMK9"}
           and feq(detail_row(dl2, "CMK9")["collected_amount"], 4760000.0)
           and feq(detail_row(dl2, "CMK9")["commission_base"], 4000000.0),
           f"got={dl2['summary']}")
        w = dl2["meta"]["warnings"]
        ck("AC-9 L2: warning de corte con conteo 4 (CMK1/2 sin tramo L2, CMK3/4 sin linea)",
           len(w) == 2 and w[1] == (f"4 collected row(s) had no participation in line "
                                    f"{state.L2} and were excluded from the settlement"),
           f"got={w}")


def ac10(cur):
    section("AC-10 - BR-45/A-11: tasa faltante pct 0 (nunca HTTP error) + desempate")
    # --- tasa global desactivada via CRUD (modo 8 de §6.1.2) ---
    r = rate_put(state.RATE_GLOB, {"is_active": False})
    if not ck("AC-10 PUT global is_active=false ⇒ 200",
              r is not None and r.status_code == 200):
        return
    try:
        data = cm_get(f"period={GOLD_PERIOD}", "AC-10-singlobal")
        if data is not None:
            # ERRATA §6.1.2 fila 8: dice 640.000 pero su propio detalle ("CMK3 y
            # CMK4 pasan a pct 0.0") implica 740.000-100.000-20.000 = 620.000.
            ck("AC-10 sin global: total 620.000 (= 740 - CMK3 100k - CMK4 20k)",
               feq(data["summary"]["total_commissions_calculated"], 620000.0),
               f"got={data['summary']['total_commissions_calculated']}")
            ck("AC-10 bloques S1 intactos (620.000), S2/S3 existen con earned 0",
               feq(seller_block(data, state.S1)["total_commission"], 620000.0)
               and feq(seller_block(data, state.S2)["total_commission"], 0.0)
               and feq(seller_block(data, state.S3)["total_commission"], 0.0))
            ok0 = True
            for rc in ("CMK3", "CMK4"):
                d = detail_row(data, rc)
                t = d["rate_details"][0] if d and d["rate_details"] else {}
                ok0 = ok0 and t.get("id_commission_rate") is None \
                    and feq(t.get("commission_pct", -1), 0.0) \
                    and feq(d["commission_earned"], 0.0) \
                    and feq(d["commission_rate_applied"], 0.0)
            ck("AC-10 CMK3/CMK4 con tramo pct 0.0, tasa null y earned 0.0 (A-11)", ok0)
            w = data["meta"]["warnings"]
            ck("AC-10 warning agrupado 'No active commission rate...' tras el de "
               "no-atribuibles (orden §6.1.3)",
               len(w) == 2 and w[0] == UNATTR_WARNING
               and w[1].startswith("No active commission rate")
               and "global (no-line) bucket" in w[1] and "2 tramo(s)" in w[1],
               f"got={w}")
    finally:
        rr = rate_put(state.RATE_GLOB, {"is_active": True})
        ck("AC-10 restaurar global (PUT is_active=true) ⇒ 200",
           rr is not None and rr.status_code == 200)
    data = cm_get(f"period={GOLD_PERIOD}", "AC-10-restaurado")
    ck("AC-10 golden restaurado (740.000 y un solo warning)",
       data is not None
       and feq(data["summary"]["total_commissions_calculated"], G_COMMISSIONS)
       and data["meta"]["warnings"] == [UNATTR_WARNING])

    # --- doble tasa L1 solapada sembrada via SQL (saltando el CRUD) ---
    did = next_id(cur, "commission_rates", "id_commission_rate")
    sql_exec(cur,
        "INSERT INTO commission_rates (id_commission_rate, id_line, rate_name, "
        "commission_pct, date_from, date_to, is_active) "
        "VALUES (%s, %s, 'CMK DUP L1 2026', 4.00, '2026-01-01', '2026-12-31', TRUE)",
        (did, state.L1))
    cur.connection.commit()
    try:
        data = cm_get(f"period={GOLD_PERIOD}", "AC-10-desempate")
        if data is not None:
            ck("AC-10 desempate: gana menor id (3 %) => total sigue 740.000",
               feq(data["summary"]["total_commissions_calculated"], G_COMMISSIONS))
            t = detail_row(data, "CMK1")["rate_details"][0]
            ck("AC-10 trazo L1 referencia la tasa de menor id con pct 3.0",
               t["id_commission_rate"] == state.RATE_L1 and feq(t["commission_pct"], 3.0),
               f"got={t}")
            w = data["meta"]["warnings"]
            ck("AC-10 warning de desempate agrupado (menor id divulgado)",
               any(x.startswith("Multiple active commission rates") and
                   "CMK-LineA" in x and
                   f"id_commission_rate={state.RATE_L1}" in x and
                   "3 tramo(s)" in x for x in w), f"got={w}")
    finally:
        sql_exec(cur, "DELETE FROM commission_rates WHERE id_commission_rate = %s", (did,))
        cur.connection.commit()
    data = cm_get(f"period={GOLD_PERIOD}", "AC-10-limpio")
    ck("AC-10 tras limpiar la tasa duplicada: warnings vuelven a [no-atribuibles]",
       data is not None and data["meta"]["warnings"] == [UNATTR_WARNING])


def ac12_readonly(cur):
    section("AC-12 - BR-49: motor 100% lectura (conteos antes/despues)")
    before = source_counts(cur)
    ok_http = True
    for _ in range(5):
        r = api("GET", f"{CMK_URL}?period={GOLD_PERIOD}")
        if r is None or r.status_code != 200:
            ok_http = False
    ck("AC-12 5 llamadas GET /commissions responden 200", ok_http)
    after = source_counts(cur)
    ck("AC-12 conteos identicos en las 7 tablas leidas + commission_rates (+maestros)",
       before == after, f"before={before} after={after}")


def ac13(cur):
    section("AC-13 - CRUD de tasas (D-3): validaciones y ciclo completo")
    # POST limpio en grupo L1 pero ventana 2027 (no interfiere con el golden)
    r = rate_post({"id_line": state.L1, "rate_name": "CMK CRUD 2027",
                   "commission_pct": 5.00, "date_from": "2027-01-01",
                   "date_to": "2027-06-30"})
    ok = r is not None and r.status_code == 200
    ck("AC-13 POST valida ⇒ 200", ok, r.text[:120] if r is not None else "sin conexion")
    crud_id = r.json()["id_commission_rate"] if ok else None

    r = rate_post({"id_line": state.L1, "rate_name": "CMK CRUD OVERLAP",
                   "commission_pct": 6.00, "date_from": "2027-03-01",
                   "date_to": "2027-12-31"})
    ck("AC-13 POST solape mismo grupo ⇒ 400 con literal E-CR-2 exacto",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E_CR_2_DETAIL,
       f"status={r.status_code if r is not None else '?'} "
       f"detail={r.json().get('detail') if r is not None else ''}")

    r = rate_post({"id_line": None, "rate_name": "CMK CRUD BADPCT",
                   "commission_pct": 101, "date_from": RATE_FROM, "date_to": RATE_TO})
    ck("AC-13 POST commission_pct=101 ⇒ 422 nativo Field (E-CM-3)",
       r is not None and r.status_code == 422)

    r = rate_post({"id_line": state.L2, "rate_name": "CMK CRUD INVERT",
                   "commission_pct": 1.0, "date_from": "2027-05-01",
                   "date_to": "2027-04-01"})
    ck("AC-13 POST vigencia invertida ⇒ 400 con literal E-CR-1 exacto",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E_CR_1_DETAIL,
       f"detail={r.json().get('detail') if r is not None and r.text else ''}")

    r = rate_post({"id_line": 999999, "rate_name": "CMK CRUD BADFK",
                   "commission_pct": 1.0, "date_from": "2028-01-01",
                   "date_to": "2028-12-31"})
    ck("AC-13 POST id_line inexistente ⇒ 404 (Exceptions Line)",
       r is not None and r.status_code == 404)

    if crud_id is not None:
        r = rate_put(crud_id, {"rate_name": "CMK CRUD 2027-R"})
        ck("AC-13 PUT merge parcial: solo cambia rate_name; pct/fechas intactos",
           r is not None and r.status_code == 200
           and r.json()["rate_name"] == "CMK CRUD 2027-R"
           and feq(r.json()["commission_pct"], 5.0)
           and r.json()["date_from"] == "2027-01-01",
           r.json() if r is not None else "sin conexion")

        r = rate_put(crud_id, {"date_from": "2027-12-01"})
        ck("AC-13 PUT vigencia invertida (merge) ⇒ 400 E-CR-1",
           r is not None and r.status_code == 400
           and r.json().get("detail") == E_CR_1_DETAIL)

        r = rate_put(999999, {"is_active": False})
        ck("AC-13 PUT id inexistente ⇒ 404", r is not None and r.status_code == 404)
        r = api("GET", f"{CR_URL}/999999")
        ck("AC-13 GET id inexistente ⇒ 404", r is not None and r.status_code == 404)
        r = api("DELETE", f"{CR_URL}/999999")
        ck("AC-13 DELETE id inexistente ⇒ 404", r is not None and r.status_code == 404)

        r = api("GET", f"{CR_URL}/{crud_id}")
        ck("AC-13 GET by id ⇒ 200 con la fila creada por API",
           r is not None and r.status_code == 200
           and r.json()["id_commission_rate"] == crud_id)

        # PUT is_active=false tambien saca de RESOLUCION (no solo de la lista):
        # se demuestra con la tasa L1 del golden en AC-13b
        r = api("DELETE", f"{CR_URL}/{crud_id}")
        ck("AC-13 DELETE fisico ⇒ 200 con message",
           r is not None and r.status_code == 200
           and "deleted successfully" in r.json().get("message", ""))
        r = api("GET", f"{CR_URL}/{crud_id}")
        ck("AC-13 tras DELETE la fila ya no existe (404 fisico)",
           r is not None and r.status_code == 404)

    # filtros de lista: la tabla debe tener exactamente las 3 tasas golden
    r = api("GET", f"{CR_URL}/")
    ck("AC-13 GET lista sin filtros ⇒ 3 filas (golden)",
       r is not None and r.status_code == 200 and len(r.json()) == 3,
       f"got={len(r.json()) if r is not None and r.status_code == 200 else '?'}")
    r = api("GET", f"{CR_URL}/?id_line={state.L1}&active_only=true&date={GOLD_TO}")
    ck("AC-13 GET ?id_line&active_only&date ⇒ 1 (L1 vigente al 25-sep)",
       r is not None and r.status_code == 200 and len(r.json()) == 1
       and r.json()[0]["id_commission_rate"] == state.RATE_L1)
    r = api("GET", f"{CR_URL}/?date=2025-06-01")
    ck("AC-13 GET ?date fuera de vigencia ⇒ 0 filas",
       r is not None and r.status_code == 200 and r.json() == [])

    # AC-13b: PUT is_active=false saca de resolucion => los tramos L1 caen a
    # la tasa global (2 %): total 740 - 120 (3%->2% en CMK1/2/9-L1) = 560.000
    r = rate_put(state.RATE_L1, {"is_active": False})
    ok = r is not None and r.status_code == 200
    ck("AC-13b PUT L1 is_active=false ⇒ 200", ok)
    if ok:
        try:
            data = cm_get(f"period={GOLD_PERIOD}", "AC-13b")
            if data is not None:
                t = detail_row(data, "CMK1")["rate_details"][0]
                ck("AC-13b tramo L1 cae a global (id=RATE_GLOB, pct 2.0), total 560.000",
                   t["id_commission_rate"] == state.RATE_GLOB
                   and feq(t["commission_pct"], 2.0)
                   and feq(data["summary"]["total_commissions_calculated"], 560000.0),
                   f"got={t}")
        finally:
            rr = rate_put(state.RATE_L1, {"is_active": True})
            ck("AC-13b reactivar L1 ⇒ 200", rr is not None and rr.status_code == 200)
    data = cm_get(f"period={GOLD_PERIOD}", "AC-13b-restaurado")
    ck("AC-13b golden intacto tras el ciclo (740.000)",
       data is not None
       and feq(data["summary"]["total_commissions_calculated"], G_COMMISSIONS))


def regress_snapshot(label):
    """Captura pnl / cash-flow / cash-flow-projection para AC-14."""
    snap = {}
    for key, url in (("pnl", f"{PNL_URL}?date_from={GOLD_FROM}&date_to={GOLD_TO}"),
                     ("cashflow", f"{CF_URL}?{CF_PARAMS}"),
                     ("projection", f"{PROJ_URL}?budget_year=2026")):
        r = api("GET", url)
        snap[key] = json.dumps(r.json(), sort_keys=True) \
            if r is not None and r.status_code == 200 else None
    state.regress[label] = snap
    return all(v is not None for v in snap.values())


def ac14_regression_final(cur):
    section("AC-14 - regresion in-bateria: pilares 1/2/legado byte-a-byte")
    ok_all = True
    for key in ("pnl", "cashflow", "projection"):
        url = {"pnl": f"{PNL_URL}?date_from={GOLD_FROM}&date_to={GOLD_TO}",
               "cashflow": f"{CF_URL}?{CF_PARAMS}",
               "projection": f"{PROJ_URL}?budget_year=2026"}[key]
        r = api("GET", url)
        after = json.dumps(r.json(), sort_keys=True) \
            if r is not None and r.status_code == 200 else None
        ok = after is not None and after == state.regress["before"].get(key)
        ck(f"AC-14 {key} identico antes/despues de toda la battery", ok)
        ok_all = ok_all and ok
    return ok_all


def ac15_errors():
    section("AC-15 - catalogos de error E-CM-1..4 (y CRUD E-CR ya en AC-13)")
    r = api("GET", CMK_URL)
    ck("E-CM-1 sin period ni fechas ⇒ 400 literal",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E_CM_1_DETAIL,
       f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{CMK_URL}?date_from={GOLD_FROM}")
    ck("E-CM-1 solo date_from ⇒ 400 mismo literal",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E_CM_1_DETAIL)
    r = api("GET", f"{CMK_URL}?date_from={GOLD_TO}&date_to={GOLD_FROM}")
    ck("E-CM-1 date_from > date_to ⇒ 400 literal compartido E-1/02_09",
       r is not None and r.status_code == 400
       and r.json().get("detail") == E_CM_1B_DETAIL,
       f"detail={r.json().get('detail') if r is not None and r.text else ''}")
    r = api("GET", f"{CMK_URL}?period={GOLD_PERIOD}&id_seller=999999")
    ck("E-CM-2 id_seller inexistente ⇒ 404 (Seller)",
       r is not None and r.status_code == 404, f"status={r.status_code if r else '?'}")
    r = api("GET", f"{CMK_URL}?period={GOLD_PERIOD}&id_line=999999")
    ck("E-CM-2 id_line inexistente ⇒ 404 (Line)",
       r is not None and r.status_code == 404)
    r = api("GET", f"{CMK_URL}?period=2026-13")
    ck("E-CM-3 period=2026-13 ⇒ 422 con detail 'period must be YYYY-MM'",
       r is not None and r.status_code == 422
       and r.json().get("detail") == E_CM_3_DETAIL,
       f"status={r.status_code if r is not None else '?'} "
       f"detail={r.json().get('detail') if r is not None and r.text else ''}")
    r = api("GET", f"{CMK_URL}?period=2026-9")
    ck("E-CM-3 period=2026-9 ⇒ 422 (regex estricta)",
       r is not None and r.status_code == 422
       and r.json().get("detail") == E_CM_3_DETAIL)
    r = api("GET", f"{CMK_URL}?period=2026-09&id_line=abc")
    ck("E-CM-3 id_line no-numerico ⇒ 422 nativo",
       r is not None and r.status_code == 422)
    r = api("GET", f"{CMK_URL}?period={GOLD_PERIOD}", auth=False)
    ck("E-CM-4 GET /commissions sin JWT ⇒ 401/403",
       r is not None and r.status_code in (401, 403),
       f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{CR_URL}/", auth=False)
    ck("E-CM-4 GET /commission-rates/ sin JWT ⇒ 401/403",
       r is not None and r.status_code in (401, 403))
    r = api("POST", f"{CR_URL}/", auth=False,
            json={"id_line": None, "rate_name": "CMK NOAUTH", "commission_pct": 1,
                  "date_from": RATE_FROM, "date_to": RATE_TO})
    ck("E-CM-4 POST /commission-rates/ sin JWT ⇒ 401/403",
       r is not None and r.status_code in (401, 403))


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Commission Engine Smoke Tests - spec backend.02_11 v1.0")
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
        section("Fase 0 - pre-clean de residuos CMK")
        clean_cmk(cur, "pre-clean")
        state.counts_initial = source_counts(cur)
        print(f"  [info] snapshot inicial: {state.counts_initial}")

        if not do_login():
            raise RuntimeError("Login fallido: no se puede continuar")
        ac01(cur)

        # ── seed golden §11: cadena FK completa con MAX+1 ──
        section("Seed golden CMK (usuarios, catalogos, customers, facturas, ledger)")
        seed_users(cur)
        seed_catalogs(cur)
        seed_customers_orders(cur)
        seed_invoices(cur)
        seed_ledger(cur)
        quarantine_conflicts(cur)
        if not seed_rates_via_api():
            raise RuntimeError("Seed de tasas por API fallo: no se puede continuar")
        print(f"  [info] S1={state.S1} S2={state.S2} S3={state.S3} "
              f"L1={state.L1} L2={state.L2} R1={state.RATE_L1} R2={state.RATE_L2} "
              f"R3={state.RATE_GLOB}")

        # ── AC-14: baseline de los otros pilares, YA con el seed visible
        #    (las filas CMK CASH-in viven solo durante esta battery: los
        #    smokes 02_09/02_10 se corren aparte sobre BD limpia) ──────────
        section("AC-14 - baseline pnl/cash-flow/projection post-seed")
        if not regress_snapshot("before"):
            ck("AC-14 baseline capturado", False, "algún endpoint no respondió 200")

        ac02(cur)
        ac03(cur)
        ac04(cur)
        ac05(cur)
        ac06(cur)
        ac07(cur)
        ac08(cur)
        ac09(cur)
        ac10(cur)
        ac13(cur)
        ac12_readonly(cur)
        ac14_regression_final(cur)
        ac15_errors()
        br48_all()
    except Exception:
        crashed = True
        print()
        traceback.print_exc()
        ck("RUN - ejecución sin excepciones no capturadas", False, "ver traceback arriba")
    finally:
        # ── fase final: restaurar cuarentenas + post-clean + AC-16 ──
        section("Fase final - restauración y limpieza garantizada (AC-16)")
        try:
            clean_cmk(cur, "post-clean")
            restore_quarantined(cur)
            ck("AC-16 cero filas CMK en ledger/invoices/customers/users",
               sql_scalar(cur, "SELECT count(*) FROM payment_ledger "
                               "WHERE receipt_number LIKE 'CMK%'") == 0
               and sql_scalar(cur, f"SELECT count(*) FROM invoices WHERE "
                                   f"invoice_number IN {INV_IN}") == 0
               and sql_scalar(cur, "SELECT count(*) FROM customers WHERE "
                                   "company_name LIKE 'CMK%'") == 0
               and sql_scalar(cur, f"SELECT count(*) FROM users WHERE document IN "
                                   f"({DOC_S1},{DOC_S2},{DOC_S3})") == 0)
            ck("AC-16 cero filas CMK en catalogos/maestros, tasas y prole de triggers",
               sql_scalar(cur, "SELECT count(*) FROM lines WHERE line_name LIKE 'CMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM brands WHERE brand_name LIKE 'CMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM product_references WHERE reference LIKE 'CMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM commission_rates WHERE rate_name LIKE 'CMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM invoice_details WHERE description = 'CMK'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM activities a JOIN customer_trips ct "
                                   "ON ct.id_customer_trip = a.id_customer_trip "
                                   "JOIN customers c ON c.id_customer = ct.id_customer "
                                   "WHERE c.company_name LIKE 'CMK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM ratings r JOIN customers c "
                                   "ON c.id_customer = r.id_customer "
                                   "WHERE c.company_name LIKE 'CMK%'") == 0)
            counts_final = source_counts(cur)
            ck("AC-16 conteos == snapshot inicial (BD intacta, motor y seed idempotentes)",
               counts_final == state.counts_initial,
               f"final={counts_final} initial={state.counts_initial}")
            if state.quarantined_rate_ids:
                still_off = sql_scalar(
                    cur, "SELECT count(*) FROM commission_rates "
                         "WHERE id_commission_rate = ANY(%s) AND NOT is_active",
                    (state.quarantined_rate_ids,))
                ck("AC-16 cuarentenas de tasas restauradas a activas", still_off == 0,
                   f"apagadas={still_off}")
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
