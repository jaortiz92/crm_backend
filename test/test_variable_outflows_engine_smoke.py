"""
Variable Outflows Engine Smoke (backend.02_28 — variable_outflows)

Spec: crm_backend/spec/backend.02_28_Spec_Backend_variable_expense_outflows.md
§8. Patron de test_budget_iva_smoke.py: corre contra el backend dev real
(:8003) con JWT de .env_test y SQL de apoyo por psycopg2 (fallback docker
exec psql). Anio de prueba AISLADO 2035 (los reales 2026/2027 jamas se
tocan); escenarios 'VOF *', CECOS '998730'/'998731' y Lineas 'SMOKE VOF *'
desechables, con pre-clean y post-clean GARANTIZADOS (try/finally).

Cubre (numerales de spec backend.02_28 / madre 04):
     AC-BE-VS-3 (fórmula completa §5.5): la Base(m) que el motor usa
                para el aporte es AP(m) + Fixed(m) [filtro ap_keys] +
                SalesVar(m) + ReceivVar(m) + Financing(m) [solo CAPITAL
                de creditos ACTIVE/projected por principal_due_date] +
                Impuestos(m) [balance_payable por payment_date +
                cash_advance por advance_cash_date] — y la respuesta
                vale Salidas(m) = Direct(m) + Σ tasas x Base(m), EXACTA
                (±0.01) para los 12 meses (Direct = AP+Fixed+SV+RV, lo
                que la API devolvia antes; la financiacion/impuestos
                SOLO alimentan la espejo de Base, compatibilidad §11).
                La base EXCLUYE el resultado de TODAS las lineas
                variable_outflows (determinista, BR-VS-01); el aporte
                usa el mes de budget_date (BR-VS-02).
     BR-VS-06 (identidad): outflows_after[m] - Base[m] == Σ aportes(m),
                verificado contra la composicion calculada
                INDEPENDIENTEMENTE por SQL del test (no contra internals
                del motor).
     AC-BE-VS-4 (multi-CECO/multi-linea): DOS lineas variable_outflows en
                CECOS distintos el MISMO mes (0.004 c/u) suman 0.008 x
                Base(mes) al total (cada linea aporta independiente,
                BR-VS-03; el CECO no altera la base).
     AC-BE-VS-5 (filtro de anio): linea variable_outflows con
                budget_date 2036 (sembrada por SQL, el CRUD lo rechaza
                via BR-LINE-04) NO aporta nada al anio 2035.
     AC-BE-VS-2 (ingesta plantilla): upload planning (ingresos + gastos)
                con una fila 'Variable por Salidas' (comportamiento) ->
                behavior_type='variable_outflows', variable_rate=0.004 y
                projected_amount=0 (AC-UP-1 generico sin cambio).
     'Sin tasa' (BR-VS-02/§8e): linea variable_outflows con
                variable_rate NULL (dirt data) aporta 0.

Los numeros absolutos del §2 (Base(Ene)=72.375.235,31 con presupuesto 576)
son un smoke MANUAL del escenario real; esta prueba replica la MISMA
identidad/formula con un fixture sintetico (nota §10 de la spec).

Uso:
    1. docker compose -f docker-compose-dev.yaml up   (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD
    3. python test/test_variable_outflows_engine_smoke.py  (desde crm_backend/)
       — requiere el interprete con las deps del backend
       (venv_backend/Scripts/python.exe) para la seccion ETL in-process.
    Tambien coleccionable por pytest via
    test_variable_outflows_engine_smoke_e2e()
    (python -m pytest test/test_variable_outflows_engine_smoke.py -x -q).
"""

import sys
import traceback
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
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

INCOME_EXCEL = Path(_cfg("INCOME_EXCEL_PATH")
                    or TEST_DIR / "data" / "Formato Solicitud Presupuesto Ingresos.xlsx")
EXPENSE_EXCEL = Path(_cfg("EXPENSE_EXCEL_PATH")
                     or TEST_DIR / "data" / "Formato Solicitud Presupuesto Gastos.xlsx")

PG_HOST = _cfg("PG_HOST", "127.0.0.1")
PG_PORT = int(_cfg("PG_PORT", "5433"))
PG_USER = _cfg("PG_USER") or dev_config.get("POSTGRES_USER", "postgres")
PG_PASSWORD = _cfg("PG_PASSWORD") or dev_config.get("POSTGRES_PASSWORD", "")
PG_DB = _cfg("PG_DB") or dev_config.get("POSTGRES_DB", "crm")
PG_DOCKER = _cfg("PG_DOCKER_CONTAINER", "db_crm_dev")

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)
for p in (INCOME_EXCEL, EXPENSE_EXCEL):
    if not p.exists():
        print(f"ERROR: falta el archivo Excel {p}")
        sys.exit(1)

# ══════════════════════════════════════════════════════════════
# CONSTANTES DEL TEST
# ══════════════════════════════════════════════════════════════

MARK = "VOF "             # prefijo de aislamiento de nombres de budgets
LINE_MARK = "SMOKE VOF"   # prefijo de aislamiento de line_name
CC_CODES = ("998730", "998731")
YEAR = 2035               # anio AISLADO (los reales jamas se tocan)
TOL = 0.01                # tolerancia COP de la identidad BR-VS-06

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Fixture del motor (todo en 2035):
#   ingresos   cc A: 100M facturacion ene (pago 20-ene), 50M feb (pago 15-feb)
#   fijo       cc A: 10M pago 15-ene
#   var ventas cc A: tasa 0.10 ene (base facturacion ene 100M -> 10M)
#   var recaudo cc A: tasa 0.20 ene (base recaudo ene 100M -> 20M)
#   financiacion    : CAPITAL 2M vence 28-ene (credito ACTIVE/projected)
#   impuestos       : balance 3M vence 25-ene + advance 1M cobrado 10-feb
#   var salidas  A  : tasa 0.004 budget_date 01-ene (cc A)
#   var salidas  B  : tasa 0.004 budget_date 15-ene (cc B) -> ene Σ 0.008
#   var salidas  B2 : tasa 0.002 budget_date 01-feb (cc B)
#   var salidas  X  : tasa NULL  budget_date 20-feb (cc B) -> aporta 0
INC1, INC2 = 100_000_000.0, 50_000_000.0
FIX1 = 10_000_000.0
RATE_VS, RATE_VR = 0.10, 0.20
FIN_PRINCIPAL = 2_000_000.0
TAX_BALANCE, TAX_ADVANCE = 3_000_000.0, 1_000_000.0
RATE_VO_A, RATE_VO_B, RATE_VO_FEB = 0.004, 0.004, 0.002

# Tasas variable_outflows por MES de budget_date (ene: A + B; feb: B2)
VO_RATES_BY_MONTH = {1: RATE_VO_A + RATE_VO_B, 2: RATE_VO_FEB}

state = type("S", (), {})()
state.headers = {}
state.token = None
state.lines = {}            # letter -> id_line (producto)
state.ccs = {}              # letter -> id_cost_center
state.b_engine = None       # presupuesto del motor 2035
state.etl_budget = None     # presupuesto del upload ETL 2035
state.vo_ids = {}           # lineas variable_outflows del motor
state.total = 0
state.passed = 0
state.failed = 0
state.results = []

# ══════════════════════════════════════════════════════════════
# UTILIDADES (patron de test_budget_iva_smoke.py)
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


def insert_budget(name, year, status_kind="draft"):
    return int(sql_scalar(
        "INSERT INTO budgets (budget_name, budget_year, budget_period, status)"
        f" VALUES ('{name}', {year}, 'ANUAL', '{status_kind}') "
        "RETURNING id_budget"))


def insert_line(budget_id, cc, ltype, bdate, pdate, amount, desc,
                behavior="FIXED", rate=None):
    p = f"'{pdate}'" if pdate else "NULL"
    r = str(rate) if rate is not None else "NULL"
    return int(sql_scalar(
        "INSERT INTO budget_lines (id_budget, id_cost_center, line_type, "
        "budget_date, payment_date, projected_amount, description, "
        "behavior_type, variable_rate) VALUES "
        f"({budget_id}, {cc}, '{ltype}', '{bdate}', {p}, {amount}, "
        f"'{desc}', '{behavior}', {r}) RETURNING id_budget_line"))


def projection(budget_id, year=YEAR):
    """GET /budget/analytics/cash-flow-projection -> {mes: salidas}."""
    r = api("GET", f"/budget/analytics/cash-flow-projection"
                   f"?budget_year={year}&id_budget={budget_id}")
    if r is None or r.status_code != 200:
        ck(f"cash-flow-projection({budget_id}) 200", False,
           (r.text[:120] if r is not None else "error"))
        return None
    return {int(row["payment_month"]): float(row["expected_outflows"])
            for row in r.json()}


def sweep():
    """Limpieza SOLO por marca/anio aislado (los reales jamas se tocan)."""
    bids = run_sql(f"SELECT id_budget FROM budgets WHERE budget_name "
                   f"LIKE '{MARK}%' AND budget_year = {YEAR}", fetch=True) or []
    bid_list = ",".join(str(b[0]) for b in bids) or "NULL"
    run_sql(f"DELETE FROM budget_tax_results WHERE id_budget IN ({bid_list})")
    run_sql(f"DELETE FROM budget_tax_assumptions WHERE id_budget IN ({bid_list})")
    run_sql(f"DELETE FROM financing_credits WHERE name LIKE '{MARK}%'")
    run_sql(f"DELETE FROM budget_lines WHERE id_budget IN ({bid_list})")
    run_sql(f"DELETE FROM budgets WHERE id_budget IN ({bid_list})")
    run_sql(f"DELETE FROM cost_centers WHERE cost_center_code IN {CC_CODES}")
    run_sql(f"DELETE FROM lines WHERE line_name LIKE '{LINE_MARK}%'")
    run_sql(f"DELETE FROM tax_profiles WHERE profile_name LIKE '{MARK}%'")


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
            f"{CC_CODES}"))
        rest_ln = int(sql_scalar(
            f"SELECT count(*) FROM lines WHERE line_name LIKE '{LINE_MARK}%'"))
        rest_fin = int(sql_scalar(
            f"SELECT count(*) FROM financing_credits WHERE name LIKE '{MARK}%'"))
        rest_tax = int(sql_scalar(
            f"SELECT count(*) FROM tax_profiles WHERE profile_name LIKE '{MARK}%'"))
        return ck("Limpieza garantizada: 0 restos (budgets/CECO/Lineas/"
                  "credito/perfil tributario)",
                  rest_b == 0 and rest_cc == 0 and rest_ln == 0
                  and rest_fin == 0 and rest_tax == 0,
                  f"budgets={rest_b} ceco={rest_cc} lines={rest_ln} "
                  f"fin={rest_fin} taxp={rest_tax}")
    except Exception:
        traceback.print_exc()
        return False


def find_col(df, needle):
    return next(c for c in df.columns
                if needle.lower() in str(c).lower())


def make_2035_xlsx(src, mutations):
    """Copia el formato SIIGO largo con TODAS las fechas movidas al anio
    2035 (BR-LINE-04 exige year del escenario) y las celdas extra
    alteradas. Reescribe con startrow=7 (contrato de lectura skiprows=7)."""
    df = pd.read_excel(src, engine="openpyxl", skiprows=7)
    dcol = find_col(df, "proyectada")
    df[dcol] = datetime(YEAR, 1, 15)
    for col_match, value, row in mutations:
        col = find_col(df, col_match)
        df.loc[row, col] = value
    # segunda columna de fecha (gasto + pago en el formato de gastos)
    for extra in ("pago",):
        try:
            ecol = find_col(df, extra)
        except StopIteration:
            continue
        if ecol != dcol:
            df[ecol] = datetime(YEAR, 1, 25)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=7)
    bio.seek(0)
    return bio


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


def t02_setup_fixtures():
    """Lineas/CECOS desechables + presupuesto 2035 con la base completa:
    ingresos, fijo, variable_sales, variable_receivables, credito de
    financiacion (CAPITAL 2M ene) y resultado de impuestos (3M ene +
    advance 1M feb)."""
    for i, letter in enumerate(("A", "B")):
        state.lines[letter] = int(sql_scalar(
            "INSERT INTO lines (id_line, line_name) VALUES "
            "((SELECT max(id_line) + 1 FROM lines), "
            f"'{LINE_MARK} {letter}') RETURNING id_line"))
        state.ccs[letter] = int(sql_scalar(
            "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
            "cost_center_name, is_active, description, id_line) VALUES "
            "((SELECT max(id_cost_center) + 1 FROM cost_centers), "
            f"'{CC_CODES[i]}', '{LINE_MARK} cc{letter}', true, "
            f"'backend.02_28 smoke: cc{letter}', {state.lines[letter]}) "
            "RETURNING id_cost_center"))
    ck("Setup: 2 Lineas + 2 CECOS desechables (max+1, nota purchases smoke)",
       len(state.lines) == 2 and len(state.ccs) == 2)

    a, b = state.ccs["A"], state.ccs["B"]
    state.b_engine = insert_budget(MARK + "engine 2035", YEAR)
    insert_line(state.b_engine, a, "INCOME", "2035-01-10", "2035-01-20",
                INC1, "VOF ingreso ene 100M")
    insert_line(state.b_engine, a, "INCOME", "2035-02-10", "2035-02-15",
                INC2, "VOF ingreso feb 50M")
    insert_line(state.b_engine, a, "EXPENSE", "2035-01-05", "2035-01-15",
                FIX1, "VOF fijo ene 10M")
    insert_line(state.b_engine, a, "EXPENSE", "2035-01-12", None, 0,
                "VOF var facturacion 10pct", behavior="VARIABLE_SALES",
                rate=RATE_VS)
    insert_line(state.b_engine, a, "EXPENSE", "2035-01-12", None, 0,
                "VOF var recaudo 20pct", behavior="VARIABLE_RECEIVABLES",
                rate=RATE_VR)

    # Credito de financiacion ACTIVE (legacy) con CAPITAL 2M venciendo
    # 2035-01-28 (solo principal: los interes/seguros ya entran como
    # lineas FIXED materializadas — §5.5 Financing(m)).
    fin_id = int(sql_scalar(
        "INSERT INTO financing_credits (name, lender_name, status, "
        "origin_type, id_cost_center, method, cutoff_date, opening_balance, "
        "annual_rate, rate_convention, day_count_convention, frequency, "
        "term_installments, first_due_date, insurance_per_installment) "
        f"VALUES ('{MARK}credito', 'SMOKE LENDER', 'active', 'legacy', "
        f"{a}, 'french_fixed_payment', '2034-12-31', 20000000, 0.12, "
        "'nominal_annual', 'monthly_periodic', 'monthly', 12, '2035-01-28', "
        "0) RETURNING id_financing_credit"))
    run_sql(
        "INSERT INTO financing_credit_installments (id_financing_credit, "
        "installment_number, period_start, period_end, principal_amount, "
        "principal_due_date, interest_amount, interest_due_date, "
        "insurance_amount, insurance_due_date, opening_balance, "
        "closing_balance, rate_used, rate_convention, day_count_convention, "
        "method, id_cost_center, schedule_revision, projection_status) "
        f"VALUES ({fin_id}, 1, '2035-01-01', '2035-01-31', {FIN_PRINCIPAL}, "
        "'2035-01-28', 0, '2035-01-28', 0, '2035-01-28', 20000000, "
        "18000000, 0.01, 'nominal_annual', 'monthly_periodic', "
        f"'french_fixed_payment', {a}, 1, 'projected')")

    # Resultado de impuestos del presupuesto: balance 3M pagadero
    # 2035-01-25 + advance 1M cobrado 2035-02-10 (tax_cash_advance lee
    # calculation_trace.cash_advance; advance_cash_date -> feb).
    tp = int(sql_scalar(
        "INSERT INTO tax_profiles (profile_name, tax_year, regime, status, "
        "iva_responsible, withholding_agent, reteiva_agent, "
        f"reteica_agent) VALUES ('{MARK}perfil', {YEAR}, 'responsable', "
        "'draft', false, false, false, false) "
        "RETURNING id_tax_profile"))
    ta = int(sql_scalar(
        "INSERT INTO budget_tax_assumptions (id_budget, id_tax_profile, "
        "taxable_income_adjustments, non_deductible_expenses, "
        "exempt_income, tax_losses, tax_discounts, prior_advances, "
        "prior_withholdings, withholding_suffered, reteiva_suffered) "
        f"VALUES ({state.b_engine}, {tp}, 0, 0, 0, 0, 0, 0, 0, 0, 0) "
        "RETURNING id_budget_tax_assumption"))
    run_sql(
        "INSERT INTO budget_tax_results (id_budget, id_budget_tax_assumption, "
        "tax_type, period_start, period_end, taxable_base, tax_rate, "
        "tax_caused, advance_amount, withholding_amount, balance_payable, "
        "declaration_date, payment_date, payment_year, calculation_trace, "
        "warnings) "
        f"VALUES ({state.b_engine}, {ta}, 'IVA', '2035-01-01', '2035-01-31', "
        "1000000, 0.19, 0, 0, 0, "
        f"{TAX_BALANCE}, '2035-01-20', '2035-01-25', {YEAR}, "
        "CAST('{\"cash_advance\": "
        f"{TAX_ADVANCE}, \"advance_cash_date\": \"2035-02-10\"}}' AS json), "
        "CAST('[]' AS json))")

    return ck("Fixture: presupuesto 2035 con ingresos 100M/50M, fijo 10M, "
              "var facturacion .10, var recaudo .20, CAPITAL financiacion "
              "2M (28-ene) e impuestos 3M (25-ene) + advance 1M (10-feb)",
              state.b_engine is not None and fin_id is not None)


def _expected_base():
    """§5.5 composicion de Base(m) calculada INDEPENDIENTEMENTE por SQL
    (misma semantica que el motor: ap_keys excluye fijos ya contados en
    AP; financing solo CAPITAL; impuestos balance + advance). Devuelve
    (base, direct): base incluye financiacion + impuestos (la Base de
    BR-VS-01); direct es solo AP+Fixed+SV+RV (lo que la API devolvia
    ANTES de backend.02_28, compatibilidad §11)."""
    direct = {m: 0.0 for m in range(1, 13)}
    ap_by_cc = {}
    for m, cc, total in run_sql(
            "SELECT extract(month FROM due_date)::int, id_cost_center, "
            "COALESCE(sum(balance),0) FROM accounts_payable "
            f"WHERE extract(year FROM due_date) = {YEAR} "
            "GROUP BY 1, 2", fetch=True):
        direct[int(m)] += float(total)
        ap_by_cc[(int(m), int(cc))] = True
    for m, cc, total in run_sql(
            "SELECT extract(month FROM COALESCE(payment_date, "
            "budget_date))::int, id_cost_center, COALESCE(sum("
            "projected_amount),0) FROM budget_lines WHERE id_budget = "
            f"{state.b_engine} AND line_type = 'EXPENSE' AND behavior_type "
            f"= 'FIXED' AND extract(year FROM COALESCE(payment_date, "
            f"budget_date)) = {YEAR} GROUP BY 1, 2", fetch=True):
        if (int(m), int(cc)) not in ap_by_cc:
            direct[int(m)] += float(total)
    # SalesVar: tasa 0.10 x facturacion del CECO resuelto (A tiene ingresos
    # propios => resuelve a A) por mes de budget_date de la linea (ene).
    # ReceivVar: tasa 0.20 x recaudo del CECO resuelto por mes de cobro
    # (pago ene 100M / feb 50M), mes de budget_date de la linea (ene).
    direct[1] += RATE_VS * INC1
    direct[1] += RATE_VR * INC1
    base = dict(direct)
    # Financing: CAPITAL de creditos ACTIVE/projection projected por mes
    # de principal_due_date en el anio (global, igual que el motor).
    for m, total in run_sql(
            "SELECT extract(month FROM i.principal_due_date)::int, "
            "COALESCE(sum(i.principal_amount),0) "
            "FROM financing_credit_installments i "
            "JOIN financing_credits c ON c.id_financing_credit = "
            "i.id_financing_credit WHERE c.status = 'active' AND "
            "i.schedule_revision = c.schedule_revision AND "
            "i.projection_status = 'projected' AND i.principal_amount > 0 "
            f"AND extract(year FROM i.principal_due_date) = {YEAR} "
            "GROUP BY 1", fetch=True):
        base[int(m)] += float(total)
    # Impuestos: balance por payment_date + advance por trace date.
    for m, total in run_sql(
            "SELECT extract(month FROM payment_date)::int, "
            "COALESCE(sum(balance_payable),0) FROM budget_tax_results "
            f"WHERE id_budget = {state.b_engine} AND payment_date IS NOT "
            f"NULL AND extract(year FROM payment_date) = {YEAR} "
            "GROUP BY 1", fetch=True):
        base[int(m)] += float(total)
    for m, total in run_sql(
            "SELECT extract(month FROM "
            "COALESCE((calculation_trace->>'advance_cash_date')::date, "
            "payment_date))::int, COALESCE(sum((calculation_trace->>"
            "'cash_advance')::numeric),0) FROM budget_tax_results "
            f"WHERE id_budget = {state.b_engine} "
            f"AND COALESCE((calculation_trace->>'advance_cash_date')::date,"
            f" payment_date) IS NOT NULL AND extract(year FROM COALESCE("
            "(calculation_trace->>'advance_cash_date')::date, "
            f"payment_date)) = {YEAR} GROUP BY 1", fetch=True):
        base[int(m)] += float(total)
    return base, direct


def t03_ac_be_vs_3_formula_and_identity():
    """AC-BE-VS-3 + BR-VS-06: la Base(m) del motor para el presupuesto
    SIN lineas variable_outflows es AP+Fixed+SalesVar+ReceivVar (lo que
    la API devolvia ANTES — compatibilidad §11, financiacion/impuestos
    solo alimentan la espejo de Base), y CON las lineas
    variable_outflows la salida vale Salidas(m) = Direct(m) + Σ tasas x
    Base(m) EXACTA (±0.01) para los 12 meses, donde Base(m) = Direct(m)
    + CAPITAL financiación + impuestos (fórmula completa §5.5, base
    compuesta por SQL INDEPENDIENTE). El aporte usa la Base CON
    financiacion/impuestos — si el motor los ignorara, el delta seria
    Σ tasas x Direct(m) y la asercion fallaria."""
    before = projection(state.b_engine)
    if before is None:
        return False
    base, direct = _expected_base()

    # ── agrega las lineas variable_outflows (2 CECOS, ene x2 + feb) ──
    a, b = state.ccs["A"], state.ccs["B"]
    state.vo_ids["A_ene"] = insert_line(
        state.b_engine, a, "EXPENSE", "2035-01-01", None, 0,
        "VOF salidas cc A ene", behavior="VARIABLE_OUTFLOWS", rate=RATE_VO_A)
    state.vo_ids["B_ene"] = insert_line(
        state.b_engine, b, "EXPENSE", "2035-01-15", None, 0,
        "VOF salidas cc B ene", behavior="VARIABLE_OUTFLOWS", rate=RATE_VO_B)
    state.vo_ids["B_feb"] = insert_line(
        state.b_engine, b, "EXPENSE", "2035-02-01", None, 0,
        "VOF salidas cc B feb", behavior="VARIABLE_OUTFLOWS",
        rate=RATE_VO_FEB)
    state.vo_ids["B_feb_null"] = insert_line(
        state.b_engine, b, "EXPENSE", "2035-02-20", None, 0,
        "VOF salidas sin tasa", behavior="VARIABLE_OUTFLOWS", rate=None)
    after = projection(state.b_engine)
    if after is None:
        return False

    ok_formula, detail_formula = True, []
    for m in range(1, 13):
        sigma = VO_RATES_BY_MONTH.get(m, 0.0)
        expected = round(direct[m] + sigma * base[m], 2)
        if abs(after[m] - expected) > TOL:
            ok_formula = False
            detail_formula.append(
                f"m{m}: got={after[m]} exp={expected} base={base[m]}")
    ck("AC-BE-VS-3/§5.5 fórmula completa: Salidas(m) = Direct(m) + Σ "
       "tasas x Base(m) para los 12 meses, con Base = AP + "
       "Fixed(ap_keys) + SalesVar + ReceivVar + CAPITAL financiación + "
       "impuestos (balance + advance) calculada por SQL independiente",
       ok_formula, "; ".join(detail_formula[:4]))

    ok_ident, detail_ident = True, []
    for m in range(1, 13):
        sigma = VO_RATES_BY_MONTH.get(m, 0.0)
        delta = round(after[m] - direct[m], 2)
        expected = round(sigma * base[m], 2)
        if abs(delta - expected) > TOL:
            ok_ident = False
            detail_ident.append(f"m{m}: delta={delta} exp={expected}")
    ck("BR-VS-06 identidad: Salidas(m) - Base(m) == Σ aportes(m) — el "
       "aporte se calcula sobre la Base CON financiación/impuestos "
       "(multi-CECO: ene acumula 0.008 x Base ene de 2 lineas; feb "
       "0.002; linea sin tasa aporta 0)", ok_ident,
       "; ".join(detail_ident[:4]))

    ok_before = all(
        abs(before[m] - round(direct[m], 2)) <= TOL
        for m in range(1, 13))
    ck("§11 compatibilidad: SIN lineas variable_outflows la respuesta "
       "es AP+Fixed+SalesVar+ReceivVar (la financiacion/impuestos solo "
       "alimentan la Base, jamas las salidas del budget sin la rama)",
       ok_before,
       f"before_ene={before[1]} direct_ene={round(direct[1], 2)} "
       f"base_ene={round(base[1], 2)}")
    return ok_formula and ok_ident and ok_before


def t04_ac_be_vs_5_year_filter():
    """AC-BE-VS-5: una linea variable_outflows con budget_date 2036 (el
    CRUD la rechaza por BR-LINE-04; aqui se siembra por SQL) NO aporta
    nada al anio 2035 — los 12 meses quedan identicos."""
    before = projection(state.b_engine)
    if before is None:
        return False
    insert_line(state.b_engine, state.ccs["A"], "EXPENSE", "2036-03-05",
                None, 0, "VOF salidas anio siguiente", 
                behavior="VARIABLE_OUTFLOWS", rate=0.5)
    after = projection(state.b_engine)
    ok = after is not None and all(
        abs(after[m] - before[m]) <= TOL for m in range(1, 13))
    return ck("AC-BE-VS-5 filtro de anio: linea budget_date 2036 (tasa "
              "0.5, ruidosa) con aporte CERO en 2035 (12 meses "
              "identicos)", ok,
              f"ene={before[1]} -> {after[1] if after else None}")


def t05_ac_be_vs_2_etl_upload():
    """AC-BE-VS-2: upload planning (ingresos + gastos) con una fila
    'Variable por Salidas' -> behavior_type='variable_outflows',
    variable_rate=0.004 y projected_amount=0 (el split monto/tasa y la
    ingesta genericos sin cambio, §5.3)."""
    exp_bio = make_2035_xlsx(EXPENSE_EXCEL, [
        ("Comportamiento", "Variable por Salidas", 0),
        ("Monto o Tasa", 0.004, 0),
        ("concepto", "VOF etl salidas", 0),
    ])
    inc_bio = make_2035_xlsx(INCOME_EXCEL, [])
    files = {
        "scenario_name": (None, MARK + "etl 2035"),
        "budget_year": (None, str(YEAR)),
        "budget_period": (None, "ANUAL"),
        "file_ingresos": ("inc.xlsx", inc_bio, XLSX_MIME),
        "file_gastos": ("exp.xlsx", exp_bio, XLSX_MIME),
    }
    r = api("POST", "/budget/planning/upload", files=files)
    if r is None or r.status_code != 201:
        return ck("AC-BE-VS-2 upload 2035 con fila 'Variable por "
                  "Salidas' -> 201", False,
                  (r.text[:180] if r is not None else "error"))
    state.etl_budget = r.json()["id_budget"]
    ck("AC-BE-VS-2 upload 201 (gastos+ingresos en 2035)",
       state.etl_budget is not None, f"body={str(r.json())[:90]}")
    raw = run_sql(
        "SELECT behavior_type, variable_rate, projected_amount FROM "
        "budget_lines WHERE id_budget = "
        f"{state.etl_budget} AND description = 'VOF etl salidas'",
        fetch=True)
    ok = (len(raw) == 1 and raw[0][0] == "VARIABLE_OUTFLOWS"
          and abs(float(raw[0][1]) - 0.004) < 1e-9
          and float(raw[0][2]) == 0.0)
    return ck("AC-BE-VS-2 fila ingesta: behavior 'VARIABLE_OUTFLOWS' "
              "(NAME), variable_rate=0.004, projected_amount=0",
              ok, f"raw={raw}")


def main():
    print("=" * 64)
    print("Variable Outflows Engine Smoke (backend.02_28)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Anio de prueba: {YEAR} | prefijo aislado: '{MARK}*'")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    print()

    tests = [
        t02_setup_fixtures,
        t03_ac_be_vs_3_formula_and_identity,
        t04_ac_be_vs_5_year_filter,
        t05_ac_be_vs_2_etl_upload,
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
# `python -m pytest test/test_variable_outflows_engine_smoke.py -x -q`).
def test_variable_outflows_engine_smoke_e2e():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
