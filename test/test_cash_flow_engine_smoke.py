"""
Cash Flow Engine (Pilar 2) Smoke Tests - spec backend.02_10 v1.0

Verificacion runtime de AC-1..AC-16 (+ E-CF-1/2/3/4/5 de errores) contra el
golden seed deterministico de §11, con marcador "CFK" para idempotencia
(pre-clean / post-clean garantizados con try/finally). Arquitectura clon del
smoke P&L (02_09): login JWT, seed SQL directo (MAX+1), cuarentena de
presupuestos active ajenos de 2026 con restore en finally, reporte N/M.

Cobertura:
  - AC-1   integracion: GET 200 con JWT + import CashFlowResponse + OpenAPI
           (ruta con $ref CashFlowResponse, 4 schemas CashFlow*, 8 params)
  - AC-2   golden §6.1.1 exacto (3 buckets, summary, meta completa, filters,
           warning de solape literal) + SQL cruzada §12.2 de cada componente
  - AC-3   D-1: modo budget => ending 19.5M; ap => 17M; both => 14M; el
           warning de solape SOLO aparece en both
  - AC-4   D-2: clamp (golden: 1.5M cae en sept, overdue 1.5M); first_bucket
           (agosto net -1.5M, accumulated 8.5M, ending identico 14M); exclude
           (ending 15.5M + warning de exclusion con conteo, orden
           exclusion->solape)
  - AC-5   D-4: sin initial_balance => starting == SQL Σ firmado CASH <
           date_from (cross-check, no literal) + warning de base relativa;
           con parametro => provided y sin warning
  - AC-6   BR-23: la fila out sembrada +500.000 (signo adverso) contribuye
           -500.000 (sept outflows exacto -9.000.000)
  - AC-7   BR-22/A-14: NON_CASH_ADJUSTMENT +9.999.999 no toca bucket, saldo
           derivado ni summary
  - AC-8   BR-26/A-12: AR vencida (6M, due 07-15) y no-deudora (-1M) fuera;
           Σ inflows == 2M+8M+3M
  - AC-9   D-3/BR-24: daily 09-14 actual / 09-15 projected; agosto mensual
           actual (end 08-31 < cutoff)
  - AC-10  BR-33/34: daily 61 | weekly 10 con primer label 2026-08-10 |
           monthly 3 (cero-fill completo)
  - AC-11  BR-35: en TODAS las respuestas capturadas ending == starting +
           Σ net y prefijos continuos; BR-23: inflows>=0, outflows<=0,
           net == inflows+outflows
  - AC-12  D-7: archivar CFK => 200, sept outflows -6M, budget_source null,
           warning literal compartido, SIN solape; clon escenario => warning
           "Comparing against scenario budget"
  - AC-13  BR-32: conteos identicos antes/despues de 5 llamadas (6 tablas)
  - AC-14  regresion: cash-flow-projection byte-a-byte antes/despues de toda
           la bateria + stubs budget-vs-actual/tracking intactos. El smoke
           02_09 (test_pnl_engine_smoke.py) se ejecuta como paso final de
           verificacion manual (misma guardia cruzada; no se sub-invoca aqui
           para no anidar cuarentenas).
  - AC-15  E-CF-1 400 literal; E-CF-3 422 con Literal (granularity/outflow_
           source/overdue_as/cutoff_date mal); E-CF-2 404 id_budget; E-CF-4
           401/403 sin token
  - AC-16  post-ejecucion: cero filas CFK en las 6 tablas + cost_centers,
           conteos == snapshot inicial, cuarentenas restauradas
  - Bridge D-3: peticion SIN cutoff_date => meta.cutoff == hoy del servidor
           (tolerante a calendario: ±1 dia por la trampa UTC de §13)

Uso:
    1. docker compose -f docker-compose-dev.yaml up -d
    2. copiar/completar .env_test (USERNAME/PASSWORD)
    3. python test/test_cash_flow_engine_smoke.py     (desde crm_backend/)
    4. guardia cruzada AC-14: python test/test_pnl_engine_smoke.py
"""

import json
import subprocess
import sys
import traceback
from datetime import date, timedelta
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

MARK = "CFK"
DFROM, DTO = "2026-08-16", "2026-10-15"     # ventana golden (date_from domingo)
CUTOFF = "2026-09-15"                        # corte falso deterministico (D-3)
INIT_BAL = "10000000"                        # saldo provisto (AC-2)
BUD_NAME = "CFK Presupuesto Caja"
CCA_CODE = "CFK-A"
CF_URL = "/budget/analytics/cash-flow"
PROJ_URL = "/budget/analytics/cash-flow-projection"
TOL = 1e-6

E_CF_1_DETAIL = "date_from must be on or before date_to"
RELATIVE_WARNING = ("starting_balance is ledger-relative: set initial_balance "
                    "for the true bank position")
NO_BUDGET_WARNING = "No active non-scenario budget for 2026"
SCENARIO_WARNING = "Comparing against scenario budget"

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
        self.CCA = None
        self.BUD = None
        # payloads capturados para AC-11 (solo respuestas cash-flow: dict)
        self.payloads = {}
        self.proj_before = None
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


def golden_params(**over):
    params = {"date_from": DFROM, "date_to": DTO, "granularity": "monthly",
              "initial_balance": INIT_BAL, "cutoff_date": CUTOFF}
    params.update(over)
    return {k: v for k, v in params.items() if v is not None}


def cf_get(params: dict, tag: str):
    """GET /cash-flow y captura del payload para AC-11. None si fallo."""
    r = api("GET", f"{CF_URL}?" + "&".join(f"{k}={v}" for k, v in params.items()))
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


def point_of(data, label):
    for p in data["time_series"]:
        if p["period"] == label:
            return p
    return None


def overlap_warning(cc, label, budget_total, ap_total):
    return (f"Potential outflow overlap (cost center {cc} in {label}): "
            f"budget expense {budget_total:.2f} and payable obligation "
            f"{ap_total:.2f} may double-count")


# ══════════════════════════════════════════════════════════════
# FASE 0: LIMPIEZA IDEMPOTENTE (marcador CFK)
# ══════════════════════════════════════════════════════════════

CLEAN_ORDER = [
    ("payable_ledger",
     "DELETE FROM payable_ledger WHERE id_account_payable IN "
     "(SELECT id_account_payable FROM accounts_payable WHERE supplier_name LIKE 'CFK%')"),
    ("accounts_payable", "DELETE FROM accounts_payable WHERE supplier_name LIKE 'CFK%'"),
    ("accounts_receivable",
     "DELETE FROM accounts_receivable WHERE document_number LIKE 'CFK%'"),
    ("payment_ledger", "DELETE FROM payment_ledger WHERE receipt_number LIKE 'CFK%'"),
    ("budget_lines",
     "DELETE FROM budget_lines WHERE id_budget IN "
     "(SELECT id_budget FROM budgets WHERE budget_name LIKE 'CFK%')"),
    ("budgets (clones)",
     "DELETE FROM budgets WHERE budget_name LIKE 'CFK%' AND parent_budget_id IS NOT NULL"),
    ("budgets", "DELETE FROM budgets WHERE budget_name LIKE 'CFK%'"),
    ("cost_centers", "DELETE FROM cost_centers WHERE cost_center_code LIKE 'CFK%'"),
]

COUNT_TABLES = [
    "payment_ledger", "accounts_receivable", "accounts_payable",
    "payable_ledger", "budget_lines", "budgets", "cost_centers",
]


def source_counts(cur):
    out = {}
    for t in COUNT_TABLES:
        out[t] = sql_scalar(cur, f"SELECT count(*) FROM {t}")
    return out


def clean_cfek(cur, phase):
    """Post/pre-clean idempotente. Un commit por sentencia: si una borra-
    cion falla no se pierden las ya ejecutadas (leccion del run piloto SMK)."""
    for table, stmt in CLEAN_ORDER:
        try:
            sql_exec(cur, stmt)
            cur.connection.commit()
        except psycopg2.Error as e:
            cur.connection.rollback()
            print(f"  [warn] {phase}: fallo limpiando {table}: "
                  f"{str(e.orig).splitlines()[0][:120]}")


# ══════════════════════════════════════════════════════════════
# CUARENTENA DE CONFLICTOS (presupuestos active ajenos de 2026 => Q0/BR-31)
# ══════════════════════════════════════════════════════════════

def quarantine_conflicts(cur):
    cur.execute(
        "SELECT id_budget FROM budgets "
        "WHERE budget_year = 2026 AND status = 'active' "
        "AND is_scenario = FALSE AND budget_name NOT LIKE 'CFK%'")
    state.quarantined_budget_ids = [r[0] for r in cur.fetchall()]
    for bid in state.quarantined_budget_ids:
        sql_exec(cur, "UPDATE budgets SET status = 'archived' WHERE id_budget = %s", (bid,))
    cur.connection.commit()
    if state.quarantined_budget_ids:
        print(f"  [info] cuarentena: {len(state.quarantined_budget_ids)} presupuestos "
              f"ajenos de 2026 (se restauran al final)")


def restore_quarantined(cur):
    for bid in state.quarantined_budget_ids:
        try:
            sql_exec(cur, "UPDATE budgets SET status = 'active' WHERE id_budget = %s", (bid,))
        except psycopg2.Error:
            cur.connection.rollback()
    cur.connection.commit()
    # verificacion: ninguna cuarentena quedo archivada por error propio
    if state.quarantined_budget_ids:
        still = sql_scalar(
            cur, "SELECT count(*) FROM budgets WHERE id_budget = ANY(%s) "
                 "AND status <> 'active'", (state.quarantined_budget_ids,))
        if still:
            print(f"  [warn] {still} presupuesto(s) en cuarentena no quedo 'active' tras restore")


# ══════════════════════════════════════════════════════════════
# SEED GOLDEN §11 (SQL directo; MAX+1 por secuencias desincronizadas del ETL)
# ══════════════════════════════════════════════════════════════

def next_id(cur, table, pk):
    return int(sql_scalar(cur, f"SELECT coalesce(max({pk}), 0) + 1 FROM {table}"))


def seed_budget(cur):
    """CECO CFK-A (sin linea) + presupuesto en draft; se activa tras la
    cuarentena para no contaminar ventanas ajenas."""
    cid = next_id(cur, "cost_centers", "id_cost_center")
    sql_exec(cur, "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
                  "cost_center_name, id_line) VALUES (%s, %s, 'CFK CECO A', NULL)",
             (cid, CCA_CODE))
    state.CCA = cid
    bid = next_id(cur, "budgets", "id_budget")
    sql_exec(cur, "INSERT INTO budgets (id_budget, budget_name, budget_year, "
                  "budget_period, status, is_scenario) "
                  "VALUES (%s, %s, 2026, 'annual', 'draft', FALSE)", (bid, BUD_NAME))
    state.BUD = bid
    # Enumes nativos PG guardan NAMES: 'EXPENSE'/'FIXED' (trampa I-7 documentada
    # en el smoke SMK)
    for bdate, amount in (("2026-09-20", 1000000), ("2026-09-30", 2000000)):
        lid = next_id(cur, "budget_lines", "id_budget_line")
        sql_exec(cur,
            "INSERT INTO budget_lines (id_budget_line, id_budget, id_cost_center, "
            "line_type, budget_date, projected_amount, description, behavior_type) "
            "VALUES (%s, %s, %s, 'EXPENSE', %s, %s, 'CFK', 'FIXED')",
            (lid, state.BUD, state.CCA, bdate, amount))
    cur.connection.commit()


def seed_ledger(cur):
    """payment_ledger: 2 de pre-saldo (julio, fuera de ventana => solo nutren
    el saldo derivado de AC-5), 2 de la ventana (la 'out' con signo INVERTIDO
    a proposito para BR-23/AC-6) y 1 NON_CASH (A-14/AC-7)."""
    rows = [
        ("CFK-IN-JUL",  "CASH", "in",  "2026-07-01",  5000000),
        ("CFK-OUT-JUL", "CASH", "out", "2026-07-20", -1200000),
        ("CFK-IN-SEP",  "CASH", "in",  "2026-09-05",  2000000),
        ("CFK-OUT-ADV", "CASH", "out", "2026-09-12",   500000),   # signo adverso
        ("CFK-NONCASH", "NON_CASH_ADJUSTMENT", None, "2026-09-08", 9999999),
    ]
    for receipt, nature, flow, pdate, amount in rows:
        pid = next_id(cur, "payment_ledger", "id_payment_ledger")
        sql_exec(cur,
            "INSERT INTO payment_ledger (id_payment_ledger, receipt_number, "
            "transaction_nature, cash_flow, payment_date, payment_amount, "
            "description) VALUES (%s, %s, %s, %s, %s, %s, 'CFK')",
            (pid, receipt, nature, flow, pdate, amount))
    cur.connection.commit()


def seed_receivables(cur):
    """AR: deudora en ventana (8M), deudora en octubre (3M), NO deudora (-1M,
    fuera por balance>0) y vencida fuera de ventana (6M, A-12)."""
    for doc, due, balance in (("CFK-AR-1", "2026-09-23",  8000000),
                              ("CFK-AR-2", "2026-10-05",  3000000),
                              ("CFK-AR-3", "2026-09-25", -1000000),
                              ("CFK-AR-4", "2026-07-15",  6000000)):
        rid = next_id(cur, "accounts_receivable", "id_account_receivable")
        sql_exec(cur,
            "INSERT INTO accounts_receivable (id_account_receivable, "
            "document_number, due_date, total_amount, paid_amount, balance) "
            "VALUES (%s, %s, %s, %s, 0, %s)", (rid, doc, due, balance, balance))
    cur.connection.commit()


def seed_payables(cur):
    """AP: vencida al corte falso (1.5M, due 09-03 < 09-15 => motor de D-2)
    y vigente (4M, due 09-30)."""
    for supplier, due, balance in (("CFK PROV-1", "2026-09-03", 1500000),
                                   ("CFK PROV-2", "2026-09-30", 4000000)):
        pid = next_id(cur, "accounts_payable", "id_account_payable")
        sql_exec(cur,
            "INSERT INTO accounts_payable (id_account_payable, id_cost_center, "
            "supplier_name, total_amount, balance, due_date) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (pid, state.CCA, supplier, balance, balance, due))
    cur.connection.commit()


def clone_budget_for_ac12(cur):
    cid = next_id(cur, "budgets", "id_budget")
    sql_exec(cur,
        "INSERT INTO budgets (id_budget, budget_name, budget_year, budget_period, "
        "status, is_scenario, parent_budget_id) "
        "SELECT %s, 'CFK CLONE 2026', budget_year, budget_period, 'draft', TRUE, id_budget "
        "FROM budgets WHERE id_budget = %s", (cid, state.BUD))
    sql_exec(cur,
        "INSERT INTO budget_lines (id_budget_line, id_budget, id_cost_center, line_type, "
        "budget_date, projected_amount, description, behavior_type) "
        "SELECT coalesce((SELECT max(id_budget_line) FROM budget_lines), 0) + "
        "row_number() OVER (), %s, id_cost_center, line_type, budget_date, "
        "projected_amount, description, behavior_type "
        "FROM budget_lines WHERE id_budget = %s", (cid, state.BUD))
    cur.connection.commit()
    return cid


# ══════════════════════════════════════════════════════════════
# SQL CRUZADA §12.2 — componentes del golden (mismos WHERE que el motor)
# ══════════════════════════════════════════════════════════════

SIGNED_SUM = ("SELECT coalesce(sum(CASE WHEN cash_flow='in' THEN abs(payment_amount) "
              "WHEN cash_flow='out' THEN -abs(payment_amount) ELSE 0 END), 0) "
              "FROM payment_ledger WHERE transaction_nature='CASH' "
              "AND cash_flow IN ('in','out')")

SQL_REAL_IN_SEP = ("SELECT coalesce(sum(abs(payment_amount)),0) FROM payment_ledger "
                   "WHERE transaction_nature='CASH' AND cash_flow='in' "
                   "AND payment_date BETWEEN '2026-09-01' AND '2026-09-30'")
SQL_REAL_OUT_SEP = ("SELECT coalesce(sum(abs(payment_amount)),0) FROM payment_ledger "
                    "WHERE transaction_nature='CASH' AND cash_flow='out' "
                    "AND payment_date BETWEEN '2026-09-01' AND '2026-09-30'")
SQL_AR_SEP = ("SELECT coalesce(sum(balance),0) FROM accounts_receivable WHERE balance > 0 "
              "AND due_date BETWEEN '2026-09-15' AND '2026-09-30'")
SQL_AR_OCT = ("SELECT coalesce(sum(balance),0) FROM accounts_receivable WHERE balance > 0 "
              "AND due_date BETWEEN '2026-10-01' AND '2026-10-15'")
SQL_AP_SEP = ("SELECT coalesce(sum(balance),0) FROM accounts_payable WHERE balance > 0 "
              "AND due_date BETWEEN '2026-09-15' AND '2026-09-30'")
SQL_AP_OVERDUE = ("SELECT coalesce(sum(balance),0) FROM accounts_payable "
                  "WHERE balance > 0 AND due_date < '2026-09-15'")
SQL_BUD_SEP = ("SELECT coalesce(sum(bl.projected_amount),0) FROM budget_lines bl "
               "WHERE bl.id_budget = %s AND bl.line_type = 'EXPENSE' "
               "AND coalesce(bl.payment_date, bl.budget_date) "
               "BETWEEN '2026-09-15' AND '2026-09-30'")


# ══════════════════════════════════════════════════════════════
# AC-11/BR-35: invariantes sobre TODA respuesta capturada
# ══════════════════════════════════════════════════════════════

def br35_all():
    section("AC-11 - BR-35/BR-23 en todas las respuestas capturadas")
    for tag, data in state.payloads.items():
        s = data["summary"]
        pts = data["time_series"]
        total = round(s["starting_balance"] + sum(p["net_flow"] for p in pts), 2)
        ck(f"{tag}:BR35 ending==start+Σnet", feq(total, s["ending_balance"]),
           f"Σ={total} ending={s['ending_balance']}")
        acc = s["starting_balance"]
        ok_pref = True
        for p in pts:
            acc = round(acc + p["net_flow"], 2)
            if not feq(acc, p["accumulated_balance"]):
                ok_pref = False
                break
        ck(f"{tag}:BR35 prefijos continuos", ok_pref, f"acc_final={acc}")
        ck(f"{tag}:BR35 summary.net_flow",
           feq(s["net_flow"], round(s["ending_balance"] - s["starting_balance"], 2)))
        ck(f"{tag}:BR23 signos (in>=0, out<=0, net=in+out)",
           all(p["inflows"] >= 0 and p["outflows"] <= 0
               and feq(p["net_flow"], p["inflows"] + p["outflows"]) for p in pts))
        # AC-7 transversal: el monto NON_CASH jamas se filtra a ningun scalar
        vals = [s["starting_balance"], s["ending_balance"], s["net_flow"]]
        vals += [x for p in pts for x in (p["inflows"], p["outflows"], p["net_flow"],
                                          p["accumulated_balance"])]
        ck(f"{tag}:AC7 sin 9.999.999 en ningun valor",
           not any(abs(v) in (9999999.0, 9999999.01, 10000008.0, 9999998.99) for v in vals))


# ══════════════════════════════════════════════════════════════
# PRUEBAS AC-1 .. AC-16
# ══════════════════════════════════════════════════════════════

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


def ac01(cur):
    section("AC-1 - integracion (200 con JWT, import de schemas, OpenAPI)")
    r = api("GET", f"{CF_URL}?" + "&".join(f"{k}={v}" for k, v in golden_params().items()))
    ck("AC-1 GET /cash-flow con JWT ⇒ 200", r is not None and r.status_code == 200,
       f"status={r.status_code if r is not None else 'sin conexion'}")
    try:
        p = subprocess.run(
            ["docker", "exec", "crm_backend_dev", "python", "-c",
             "from app.schemas import CashFlowResponse; print('IMPORT_OK')"],
            capture_output=True, text=True, timeout=120)
        ck("AC-1 from app.schemas import CashFlowResponse (en contenedor)",
           "IMPORT_OK" in p.stdout, (p.stderr or p.stdout)[:120])
    except FileNotFoundError:
        ck("AC-1 import de schemas (docker CLI no disponible)", False,
           "docker no está en el PATH del host")
    r = api("GET", "/openapi.json", auth=False)
    if r is None or r.status_code != 200:
        ck("AC-1 /openapi.json accesible", False)
        return
    spec = r.json()
    cf_path = spec.get("paths", {}).get("/budget/analytics/cash-flow", {}).get("get", {})
    ck("AC-1 ruta documentada en OpenAPI", bool(cf_path))
    ref = (cf_path.get("responses", {}).get("200", {})
           .get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", ""))
    ck("AC-1 response_model ⇒ $ref CashFlowResponse",
       ref.endswith("/CashFlowResponse"), f"ref={ref}")
    qnames = [q.get("name") for q in cf_path.get("parameters", [])]
    ck("AC-1 los 8 query params presentes",
       all(k in qnames for k in ("date_from", "date_to", "granularity", "id_budget",
                                 "initial_balance", "outflow_source", "overdue_as",
                                 "cutoff_date")), f"got={qnames}")
    schemas = spec.get("components", {}).get("schemas", {})
    ck("AC-1 schemas CashFlow* en components",
       all(n in schemas for n in ("CashFlowResponse", "CashFlowMeta",
                                  "CashFlowSummary", "CashFlowPoint")))
    ck("AC-1 cero DDL: CashFlowPoint sin tabla propia (solo 6 tablas fuente tocadas)",
       sql_scalar(cur, "SELECT to_regclass('public.cash_flow_points')") is None)


def proj_baseline(cur):
    section("AC-14 - baseline cash-flow-projection y stubs (antes de la batería)")
    r = api("GET", f"{PROJ_URL}?budget_year=2026")
    if r is not None and r.status_code == 200:
        state.proj_before = json.dumps(r.json(), sort_keys=True)
        ck("AC-14 cash-flow-projection responde 200", True)
    else:
        state.proj_before = None
        ck("AC-14 cash-flow-projection responde 200", False,
           f"status={r.status_code if r is not None else 'sin conexion'}")
    r = api("GET", "/budget/analytics/budget-vs-actual?id_budget=1")
    ck("AC-14 stub budget-vs-actual ⇒ 200 []",
       r is not None and r.status_code == 200 and r.json() == [])
    r = api("GET", "/budget/analytics/tracking/1")
    stub = r is not None and r.status_code == 200 and r.json().get("budget_name") == "" \
        and r.json().get("total_budgeted") in (0, 0.0)
    ck("AC-14 stub tracking ⇒ 200 con forma stub", stub,
       r.text[:120] if r is not None else "sin conexion")


def ac02(cur):
    section("AC-2/AC-6/AC-7/AC-8 - golden §6.1.1 exacto + SQL cruzada")
    data = cf_get(golden_params(), "AC-2")
    if data is None:
        return
    ck_keys("AC-2 summary", data["summary"],
            {"starting_balance": 10000000.0, "ending_balance": 14000000.0,
             "net_flow": 4000000.0})
    ts = data["time_series"]
    ck("AC-2 3 buckets monthly", len(ts) == 3, f"got={len(ts)}")
    if len(ts) != 3:
        return
    # agosto parcial: label 2026-08-01 (BR-34) ceros, actual
    ck_keys("AC-2 ago", ts[0], {"period": "2026-08-01", "status": "actual",
                                "inflows": 0.0, "outflows": 0.0, "net_flow": 0.0,
                                "accumulated_balance": 10000000.0})
    ck("AC-2 ago outflows serializado <= 0 (convención -0.0 del golden)",
       ts[0]["outflows"] <= 0)
    ck_keys("AC-2 sep", ts[1], {"period": "2026-09-01", "status": "projected",
                                "inflows": 10000000.0, "outflows": -9000000.0,
                                "net_flow": 1000000.0,
                                "accumulated_balance": 11000000.0})
    ck_keys("AC-2 oct", ts[2], {"period": "2026-10-01", "status": "projected",
                                "inflows": 3000000.0, "outflows": 0.0,
                                "net_flow": 3000000.0,
                                "accumulated_balance": 14000000.0})

    meta = data["meta"]
    ck_keys("AC-2 meta scalar fields", meta,
            {"granularity": "monthly", "cutoff": CUTOFF,
             "initial_balance_source": "provided", "outflow_source": "both",
             "overdue_as": "clamp_cutoff", "overdue_outflows": 1500000.0})
    ck_keys("AC-2 meta.budget_source", meta["budget_source"],
            {"id_budget": state.BUD, "budget_name": BUD_NAME, "status": "active"})
    ck("AC-2 meta.filters eco exacto de los 8 params (BR-39)", meta["filters"] == {
        "date_from": DFROM, "date_to": DTO, "granularity": "monthly",
        "id_budget": None, "initial_balance": 10000000.0, "outflow_source": "both",
        "overdue_as": "clamp_cutoff", "cutoff_date": CUTOFF}, f"got={meta['filters']}")
    ck("AC-2 warnings == [solape literal] (orden §5.6)", meta["warnings"] ==
       [overlap_warning(state.CCA, "2026-09-01", 3000000.0, 5500000.0)],
       f"got={meta['warnings']}")

    # §12.2: cada escalar dorado cruzado contra SQL con los WHERE del motor
    real_in = float(sql_scalar(cur, SQL_REAL_IN_SEP))
    ar_sep = float(sql_scalar(cur, SQL_AR_SEP))
    real_out = float(sql_scalar(cur, SQL_REAL_OUT_SEP))
    ap_sep = float(sql_scalar(cur, SQL_AP_SEP))
    ap_over = float(sql_scalar(cur, SQL_AP_OVERDUE))
    bud_sep = float(sql_scalar(cur, SQL_BUD_SEP, (state.BUD,)))
    ck("AC-2 SQL× sep.inflows == real(2M)+AR(8M)", feq(ts[1]["inflows"], real_in + ar_sep),
       f"real={real_in} ar={ar_sep} payload={ts[1]['inflows']}")
    ck("AC-2 SQL× sep.outflows == real+AP+clamp+Bud",
       feq(-ts[1]["outflows"], real_out + ap_sep + ap_over + bud_sep),
       f"SQL={real_out + ap_sep + ap_over + bud_sep} payload={-ts[1]['outflows']}")
    xsql_check(cur, "AC-2 SQL× oct.inflows == AR(3M)", SQL_AR_OCT, ts[2]["inflows"])
    xsql_check(cur, "AC-2 SQL× overdue_outflows == AP vencida al corte",
               SQL_AP_OVERDUE, meta["overdue_outflows"])

    # AC-6 (BR-23): la fila out sembrada POSITIVA contribuye como -500.000
    stored = float(sql_scalar(cur, "SELECT payment_amount FROM payment_ledger "
                                   "WHERE receipt_number = 'CFK-OUT-ADV'"))
    ck("AC-6 la fila adversa está almacenada como +500.000", feq(stored, 500000.0),
       f"stored={stored}")
    ck("AC-6 pese al signo adverso, Σ real out de la ventana == 500.000 (abs en fuente)",
       feq(real_out, 500000.0), f"SQL={real_out}")
    ck("AC-6 sept.outflows negativo en el payload (jamás +9M)", ts[1]["outflows"] < 0)

    # AC-7 (BR-22/A-14): NON_CASH existe pero no toca nada
    ck("AC-7 la fila NON_CASH_ADJUSTMENT sembrada existe",
       sql_scalar(cur, "SELECT count(*) FROM payment_ledger WHERE receipt_number = "
                       "'CFK-NONCASH' AND transaction_nature = 'NON_CASH_ADJUSTMENT'") == 1)
    ck("AC-7 Σ inflows de la serie == 2M+8M+3M (sin 9.999.999)",
       feq(sum(p["inflows"] for p in ts), 13000000.0),
       f"got={sum(p['inflows'] for p in ts)}")

    # AC-8 (BR-26/A-12): vencida y no-deudora fuera, ancla >= slice_lo
    ck("AC-8 AR vencida 6M y no-deudora -1M existen en BD pero no en la serie",
       sql_scalar(cur, "SELECT count(*) FROM accounts_receivable WHERE "
                       "document_number IN ('CFK-AR-3','CFK-AR-4')") == 2
       and not any(abs(p["inflows"] - 7000000.0) < TOL for p in ts))
    xsql_check(cur, "AC-8 SQL× Σ AR deudora en ancla [slice_lo, date_to] == 11M",
               "SELECT coalesce(sum(balance),0) FROM accounts_receivable WHERE balance > 0 "
               "AND due_date BETWEEN '2026-09-15' AND '2026-10-15'", 11000000.0)
    # AC-9 (mensual): agosto end 08-31 < cutoff ⇒ actual (ya ck_keys arriba)
    ck("AC-9 agosto actual vs sept/oct projected (bucket cruzado es projected, BR-24)",
       ts[0]["status"] == "actual" and ts[1]["status"] == "projected"
       and ts[2]["status"] == "projected")


def ac03(cur):
    section("AC-3 - D-1: matriz outflow_source (sobre el mismo seed)")
    data = cf_get(golden_params(outflow_source="budget"), "AC-3-budget")
    if data is not None:
        ck("AC-3 budget-only: ending 19.5M", feq(data["summary"]["ending_balance"], 19500000.0),
           f"got={data['summary']['ending_balance']}")
        ck("AC-3 budget-only: overdue_outflows 0.0 (Q4 ni se ejecuta)",
           feq(data["meta"]["overdue_outflows"], 0.0))
        ck("AC-3 budget-only: SIN warning de solape",
           not any("overlap" in w for w in data["meta"]["warnings"]),
           f"got={data['meta']['warnings']}")
        ck("AC-3 budget-only: sept outflows -(0.5M+3M) = -3.5M",
           feq(point_of(data, "2026-09-01")["outflows"], -3500000.0))

    data = cf_get(golden_params(outflow_source="ap"), "AC-3-ap")
    if data is not None:
        ck("AC-3 ap-only: ending 17M", feq(data["summary"]["ending_balance"], 17000000.0),
           f"got={data['summary']['ending_balance']}")
        ck("AC-3 ap-only: overdue_outflows 1.5M", feq(data["meta"]["overdue_outflows"], 1500000.0))
        ck("AC-3 ap-only: SIN warning de solape",
           not any("overlap" in w for w in data["meta"]["warnings"]))
        ck("AC-3 ap-only: sept outflows -(0.5+1.5+4) = -6M",
           feq(point_of(data, "2026-09-01")["outflows"], -6000000.0))

    data = cf_get(golden_params(outflow_source="both"), "AC-3-both")
    if data is not None:
        ck("AC-3 both: ending 14M (el solape NO se deduplica, D-1)",
           feq(data["summary"]["ending_balance"], 14000000.0))
        ck("AC-3 both: el solape SOLO aparece aquí",
           any("overlap" in w for w in data["meta"]["warnings"]))
        ck("AC-3 both: meta ecoa outflow_source", data["meta"]["outflow_source"] == "both")


def ac04(cur):
    section("AC-4 - D-2: matriz overdue_as (clamp ya cubierto por el golden)")
    data = cf_get(golden_params(overdue_as="first_bucket"), "AC-4-first")
    if data is not None:
        ago = point_of(data, "2026-08-01")
        sep = point_of(data, "2026-09-01")
        ck("AC-4 first_bucket: agosto absorbe la deuda (outflows -1.5M, net -1.5M)",
           ago is not None and feq(ago["outflows"], -1500000.0)
           and feq(ago["net_flow"], -1500000.0), f"ago={ago}")
        ck("AC-4 first_bucket: accumulated agosto == 8.5M",
           ago is not None and feq(ago["accumulated_balance"], 8500000.0))
        ck("AC-4 first_bucket: ending idéntico al clamp (invariante de ventana)",
           feq(data["summary"]["ending_balance"], 14000000.0),
           f"got={data['summary']['ending_balance']}")
        ck("AC-4 first_bucket: overdue_outflows 1.5M",
           feq(data["meta"]["overdue_outflows"], 1500000.0))
        ck("AC-4 first_bucket: solape sept con AP restante (4M)",
           data["meta"]["warnings"] ==
           [overlap_warning(state.CCA, "2026-09-01", 3000000.0, 4000000.0)],
           f"got={data['meta']['warnings']}")
        ck("AC-4 first_bucket: sept outflows -(0.5+4+3) = -7.5M",
           sep is not None and feq(sep["outflows"], -7500000.0))

    data = cf_get(golden_params(overdue_as="exclude"), "AC-4-exclude")
    if data is not None:
        ck("AC-4 exclude: ending 15.5M", feq(data["summary"]["ending_balance"], 15500000.0),
           f"got={data['summary']['ending_balance']}")
        ck("AC-4 exclude: overdue_outflows publica el monto excluido igual",
           feq(data["meta"]["overdue_outflows"], 1500000.0))
        ck("AC-4 exclude: orden de warnings exclusion → solape (§5.6)",
           data["meta"]["warnings"] ==
           ["1 past-due payable obligation(s) excluded (overdue_as=exclude)",
            overlap_warning(state.CCA, "2026-09-01", 3000000.0, 4000000.0)],
           f"got={data['meta']['warnings']}")
        ck("AC-4 exclude: agosto y sept sin deuda vencida (outflows -0 y -7.5M)",
           feq(point_of(data, "2026-08-01")["outflows"], 0.0)
           and feq(point_of(data, "2026-09-01")["outflows"], -7500000.0))


def ac05(cur):
    section("AC-5 - D-4: saldo inicial derivado vs provisto")
    params = {k: v for k, v in golden_params(initial_balance=None).items()}
    data = cf_get(params, "AC-5-derived")
    if data is None:
        return
    sql_start = float(sql_scalar(cur, SIGNED_SUM + " AND payment_date < %s", (DFROM,)))
    ck("AC-5 starting == SQL Σ firmado CASH < date_from (cross-check, no literal)",
       feq(data["summary"]["starting_balance"], sql_start),
       f"SQL={sql_start} payload={data['summary']['starting_balance']}")
    ck("AC-5 initial_balance_source == derived_from_ledger",
       data["meta"]["initial_balance_source"] == "derived_from_ledger")
    ck("AC-5 warning literal de base relativa (posición: tras selección de presupuesto)",
       data["meta"]["warnings"] ==
       [RELATIVE_WARNING, overlap_warning(state.CCA, "2026-09-01", 3000000.0, 5500000.0)],
       f"got={data['meta']['warnings']}")
    ck("AC-5 ending = derived + 4M (la curva se traslada paralela, BR-35)",
       feq(data["summary"]["ending_balance"], round(sql_start + 4000000.0, 2)))
    ck("AC-5 filters.initial_balance null ecoado",
       data["meta"]["filters"]["initial_balance"] is None)
    # AC-7: el saldo derivado TAMPOCO ve el NON_CASH de sept (fuera por fecha y
    # por filtro CASH); el cross-check de arriba ya lo demuestra con SQL propia
    # naturaleza. Verificacion extra: excluir NON_CASH de la SQL no la cambia.
    sql_all_nat = float(sql_scalar(
        cur, "SELECT coalesce(sum(CASE WHEN cash_flow='in' THEN abs(payment_amount) "
             "WHEN cash_flow='out' THEN -abs(payment_amount) ELSE 0 END),0) "
             "FROM payment_ledger WHERE cash_flow IN ('in','out') "
             "AND payment_date < %s", (DFROM,)))
    ck("AC-7 derivado insensible a NON_CASH (sin filtro nature == con filtro, cash_flow NOT NULL)",
       feq(sql_all_nat, sql_start), f"sin_nature={sql_all_nat} con_nature={sql_start}")


def ac09_daily_ac10_counts(cur):
    section("AC-9/AC-10 - estatus daily y counts de serie (cero-fill BR-33/34)")
    data = cf_get(golden_params(granularity="daily"), "AC-9-daily")
    if data is not None:
        ck("AC-10 daily: 61 puntos (08-16..10-15 inclusive)",
           len(data["time_series"]) == 61, f"got={len(data['time_series'])}")
        p14 = point_of(data, "2026-09-14")
        p15 = point_of(data, "2026-09-15")
        ck("AC-9 daily 2026-09-14 ⇒ actual (end < cutoff)",
           p14 is not None and p14["status"] == "actual")
        ck("AC-9 daily 2026-09-15 ⇒ projected (día del corte, BR-24)",
           p15 is not None and p15["status"] == "projected")
        ck("AC-9/AC-4 daily: el 1.5M clampado cae en el día del corte (09-15, out -1.5M)",
           p15 is not None and feq(p15["outflows"], -1500000.0), f"p15={p15}")

    data = cf_get(golden_params(granularity="weekly"), "AC-10-weekly")
    if data is not None:
        ck("AC-10 weekly: 10 buckets", len(data["time_series"]) == 10,
           f"got={len(data['time_series'])}")
        ck("AC-10 weekly: primer label 2026-08-10 < date_from (BR-34)",
           data["time_series"][0]["period"] == "2026-08-10",
           f"got={data['time_series'][0]['period']}")
        ck("AC-10 weekly: ending invariante BR-35 == 14M",
           feq(data["summary"]["ending_balance"], 14000000.0),
           f"got={data['summary']['ending_balance']}")


def ac12_budget_lifecycle(cur):
    section("AC-12 - D-7: sin presupuesto y escenario (literales compartidos 02_09)")
    sql_exec(cur, "UPDATE budgets SET status = 'archived' WHERE id_budget = %s", (state.BUD,))
    cur.connection.commit()
    try:
        data = cf_get(golden_params(), "AC-12-nobudget")
        if data is not None:
            ck("AC-12 sin presupuesto: budget_source null (nunca error, E-CF philosophy)",
               data["meta"]["budget_source"] is None)
            ck("AC-12 warning literal compartido con 02_09",
               data["meta"]["warnings"] == [NO_BUDGET_WARNING],
               f"got={data['meta']['warnings']}")
            ck("AC-12 salidas de presupuesto = 0.0 (sept outflows -(0.5+1.5+4) = -6M, BR-31)",
               feq(point_of(data, "2026-09-01")["outflows"], -6000000.0))
            ck("AC-12 ending 17M == modo ap (sin filas Q5 => sin solape)",
               feq(data["summary"]["ending_balance"], 17000000.0)
               and not any("overlap" in w for w in data["meta"]["warnings"]))
    finally:
        sql_exec(cur, "UPDATE budgets SET status = 'active' WHERE id_budget = %s",
                 (state.BUD,))
        cur.connection.commit()

    clone = clone_budget_for_ac12(cur)
    try:
        data = cf_get(golden_params(id_budget=clone), "AC-12-scenario")
        if data is not None:
            ck("AC-12 escenario: warning 'Comparing against scenario budget'",
               SCENARIO_WARNING in data["meta"]["warnings"],
               f"got={data['meta']['warnings']}")
            ck("AC-12 escenario: id_budget manda (budget_source = clon)",
               data["meta"]["budget_source"]
               and data["meta"]["budget_source"]["id_budget"] == clone)
            ck("AC-12 escenario: mismas líneas => valores del golden (ending 14M)",
               feq(data["summary"]["ending_balance"], 14000000.0))
    finally:
        # borrar el clon YA: project_cash_flow no filtra is_scenario y lo
        # contaría en el baseline byte-a-byte de AC-14 (lección del SMK AC-7)
        sql_exec(cur, "DELETE FROM budget_lines WHERE id_budget = %s", (clone,))
        sql_exec(cur, "DELETE FROM budgets WHERE id_budget = %s", (clone,))
        cur.connection.commit()


def ac13_readonly(cur):
    section("AC-13 - motor 100% lectura (conteos antes/después)")
    before = source_counts(cur)
    ok_http = True
    for _ in range(5):
        r = api("GET", f"{CF_URL}?" + "&".join(f"{k}={v}" for k, v in golden_params().items()))
        if r is None or r.status_code != 200:
            ok_http = False
    ck("AC-13 5 llamadas GET /cash-flow responden 200", ok_http)
    after = source_counts(cur)
    ck("AC-13 conteos idénticos en las 6 tablas fuente (+cost_centers)",
       before == after, f"before={before} after={after}")


def ac14_final(cur):
    section("AC-14 - cash-flow-projection byte-a-byte tras toda la batería")
    r = api("GET", f"{PROJ_URL}?budget_year=2026")
    after = json.dumps(r.json(), sort_keys=True) if r is not None and r.status_code == 200 else None
    ck("AC-14 cash-flow-projection idéntica antes/después (legado intacto, BR-36)",
       after is not None and after == state.proj_before)
    r = api("GET", "/budget/analytics/budget-vs-actual?id_budget=1")
    ck("AC-14 stub budget-vs-actual sigue []",
       r is not None and r.status_code == 200 and r.json() == [])
    r = api("GET", "/budget/analytics/tracking/1")
    ck("AC-14 stub tracking sigue igual (budget_name='')",
       r is not None and r.status_code == 200 and r.json().get("budget_name") == "")


def ac15_errors():
    section("AC-15 - catálogo de errores E-CF-1..5")
    r = api("GET", f"{CF_URL}?date_from=2026-10-15&date_to=2026-08-16")
    ck("E-CF-1 date_from > date_to ⇒ 400 con detail literal",
       r is not None and r.status_code == 400 and r.json().get("detail") == E_CF_1_DETAIL,
       f"status={r.status_code if r is not None else '?'}")
    for name, bad in (("granularity", "quarterly"), ("outflow_source", "mixed"),
                      ("overdue_as", "clamp"), ("cutoff_date", "2026-02-30")):
        r = api("GET", f"{CF_URL}?" + "&".join(
            f"{k}={v}" for k, v in golden_params(**{name: bad}).items()))
        ck(f"E-CF-3 {name}={bad} ⇒ 422 nativo (Literal/date)",
           r is not None and r.status_code == 422,
           f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{CF_URL}?" + "&".join(
        f"{k}={v}" for k, v in golden_params(id_budget=999999).items()))
    ck("E-CF-2 id_budget inexistente ⇒ 404 (Exceptions.register_not_found)",
       r is not None and r.status_code == 404,
       f"status={r.status_code if r is not None else '?'}")
    r = api("GET", f"{CF_URL}?" + "&".join(f"{k}={v}" for k, v in golden_params().items()),
            auth=False)
    ck("E-CF-4 sin JWT ⇒ 401/403", r is not None and r.status_code in (401, 403),
       f"status={r.status_code if r is not None else '?'}")


def bridge_cutoff(cur):
    section("Bridge D-3/BR-37 - cutoff default = hoy del servidor")
    params = {"date_from": DFROM, "date_to": DTO, "granularity": "monthly",
              "initial_balance": INIT_BAL}
    data = cf_get(params, "Bridge")
    if data is None:
        return
    today = date.today()
    allowed = {(today + timedelta(days=off)).isoformat() for off in (-1, 0, 1)}
    ck("Bridge meta.cutoff == hoy del servidor (±1 día: trampa UTC §13)",
       data["meta"]["cutoff"] in allowed, f"cutoff={data['meta']['cutoff']} hoy={today}")
    ck("Bridge filters.cutoff_date null ecoado (no se envió)",
       data["meta"]["filters"]["cutoff_date"] is None)
    ck("Bridge con cutoff real (2026-09-07 < 09-15) la ventana golden no cambia de "
       "membresía: ending 14M", feq(data["summary"]["ending_balance"], 14000000.0),
       f"got={data['summary']['ending_balance']}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Cash Flow Engine Smoke Tests - spec backend.02_10 v1.0")
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
        section("Fase 0 - pre-clean de residuos CFK")
        clean_cfek(cur, "pre-clean")
        state.counts_initial = source_counts(cur)
        print(f"  [info] snapshot inicial: {state.counts_initial}")

        if not do_login():
            raise RuntimeError("Login fallido: no se puede continuar")
        seed_budget(cur)
        quarantine_conflicts(cur)
        seed_ledger(cur)
        seed_receivables(cur)
        seed_payables(cur)
        sql_exec(cur, "UPDATE budgets SET status='active' WHERE id_budget = %s", (state.BUD,))
        conn.commit()

        proj_baseline(cur)
        ac01(cur)
        ac02(cur)
        ac03(cur)
        ac04(cur)
        ac05(cur)
        ac09_daily_ac10_counts(cur)
        ac12_budget_lifecycle(cur)
        ac13_readonly(cur)
        ac15_errors()
        bridge_cutoff(cur)
        ac14_final(cur)
        br35_all()
    except Exception:
        crashed = True
        print()
        traceback.print_exc()
        ck("RUN - ejecución sin excepciones no capturadas", False, "ver traceback arriba")
    finally:
        # ── fase final: restaurar cuarentenas + post-clean + verificación ──
        section("Fase final - restauración y limpieza garantizada")
        try:
            clean_cfek(cur, "post-clean")
            restore_quarantined(cur)
            ck("AC-16/LIMPIEZA no quedaron filas CFK en las 6 tablas + cost_centers",
               sql_scalar(cur, "SELECT count(*) FROM payment_ledger WHERE receipt_number LIKE 'CFK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM accounts_receivable WHERE document_number LIKE 'CFK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM accounts_payable WHERE supplier_name LIKE 'CFK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM payable_ledger pl WHERE pl.id_account_payable IN (SELECT id_account_payable FROM accounts_payable WHERE supplier_name LIKE 'CFK%')") == 0
               and sql_scalar(cur, "SELECT count(*) FROM budget_lines WHERE id_budget IN (SELECT id_budget FROM budgets WHERE budget_name LIKE 'CFK%')") == 0
               and sql_scalar(cur, "SELECT count(*) FROM budgets WHERE budget_name LIKE 'CFK%'") == 0
               and sql_scalar(cur, "SELECT count(*) FROM cost_centers WHERE cost_center_code LIKE 'CFK%'") == 0)
            counts_final = source_counts(cur)
            ck("AC-16/LIMPIEZA conteos == snapshot inicial (BD intacta)",
               counts_final == state.counts_initial, f"final={counts_final}")
            active_cfek = sql_scalar(
                cur, "SELECT count(*) FROM budgets WHERE budget_name LIKE 'CFK%' AND status='active'")
            ck("AC-16/LIMPIEZA ningún presupuesto CFK activo al terminar", (active_cfek or 0) == 0)
            restored = True
            for bid in state.quarantined_budget_ids:
                if sql_scalar(cur, "SELECT status FROM budgets WHERE id_budget = %s", (bid,)) != "active":
                    restored = False
            ck("AC-16/LIMPIEZA cuarentenas restauradas a active", restored,
               f"ids={state.quarantined_budget_ids}")
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
