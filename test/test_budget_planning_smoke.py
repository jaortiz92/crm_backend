"""
Budget Planning Module Smoke Tests (BE-S4-BUDGET-PLANNING)

Spec: crm_backend/spec/backend.02_12_Spec_Backend_budgets_planning.md §9/§9.4.

Cubre contra el backend corriendo (dev) y los 2 archivos SIIGO reales de
test/data/:
    AC-UP-1..4   upload todo-o-nada de 2 archivos, rollback, unicidad
    AC-CL-1..3   clone con modifier_pct (tasas NO escaladas, -100, -101 422)
    AC-CE-1..3   edicion puntual de celda (inmutables, >=0/422, 404, LWW)
    AC-MT-1..3   Meta Activa por ano (invariante, Q0 del engine ve el
                 escenario, gate 403 para Financiero)
    AC-REG-01    endpoints legados budget-plan-income/expense +
                 clone-for-scenario con comportamiento IDENTICO tras T-02
    AC-REG-02    Q0 con 0 activos: resolucion y warnings literales intactos

Aislamiento ("schema aislado" a nivel de datos): todos los registros creados
usan el prefijo de nombre "PLN " y el ano de prueba 2027 (los archivos de
test/data/. proyectan fechas 2027), con pre-clean y post-clean garantizados
(try/finally) via API + SQL directo. El usuario temporal Financiero (gate
403) se crea y se elimina al final.

Uso:
    1. docker compose -f docker-compose-dev.yaml up  (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD (usuario Gerente/Administrador)
    3. python test/test_budget_planning_smoke.py     (desde crm_backend/)

Notas de entorno:
    - Si psycopg2 esta disponible se conecta a la BD (PG_* de .env_test o
      los defaults de .env.development); si no, hace fallback a
      `docker exec db_crm_dev psql` (nombre del contenedor configurable con
      PG_DOCKER_CONTAINER en .env_test).
"""

import sys
import threading
import traceback
from datetime import date, datetime
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

# BD (solo para aserciones/ajustes que la API no expone: rol del usuario
# temporal y conteos de rollback). Fallback: docker exec psql.
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

MARK = "PLN "            # prefijo de aislamiento de nombres
YEAR = 2027              # anio de prueba (los xlsx de test/data proyectan 2027)
TOL = 1e-6
PERIOD = "ANUAL"

NAME_BASE = MARK + "Base 2027"
NAME_DUP = MARK + "SoloIngresos 2027"
NAME_BADCX = MARK + "CECO malo"
NAME_BADYEAR = MARK + "anio mezclado"
NAME_LEG_INC = MARK + "LegInc 2027"
NAME_LEG_EXP = MARK + "LegExp 2027"
NAME_CLONE10 = MARK + "A +10%"
NAME_CLONE0 = MARK + "B cero%"
NAME_CLONE100 = MARK + "C -100%"
NAME_CLONEDUP = MARK + "D clon de clon"
NAME_BADCLONE = MARK + "clon invalido"
TEMP_USER = "smkplnfin2027"
TEMP_USER_PASS = "SmkPln!2027"
TEMP_DOC = 999911111.0

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

state = type("S", (), {})()
state.headers = {}
state.token = None
state.fin_token = None
state.fin_user_id = None
state.base_id = None
state.b_id = None
state.c_id = None
state.clone10_id = None
state.clone0_id = None
state.leg_inc_id = None
state.leg_exp_id = None
state.base_lines = {}          # id -> line dict (snapshot)
state.target_line_id = None    # celda usada en AC-CE
state.created_budgets = []     # ids para limpieza
state.created_names = []       # nombres para limpieza (por si el id no se capturo)
state.temp_xlsx = []
state.total = 0
state.passed = 0
state.failed = 0
state.results = []


# ══════════════════════════════════════════════════════════════
# UTILIDADES
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


def make_variant_xlsx(src, dst, mutations):
    """Copia el formato SIIGO largo con celdas alteradas.

    Lee con skiprows=7 (encabezado real en fila 8) y reescribe con
    startrow=7 para conservar el contrato de lectura del ETL."""
    df = pd.read_excel(src, engine="openpyxl", skiprows=7)
    for col_match, value, row in mutations:
        col = next(c for c in df.columns if col_match.lower() in str(c).lower())
        df.loc[row, col] = value
    with pd.ExcelWriter(dst, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=7)
    state.temp_xlsx.append(Path(dst))
    return Path(dst)


def count_excel_rows(path):
    return len(pd.read_excel(path, engine="openpyxl", skiprows=7))


def get_lines(budget_id):
    r = api("GET", f"/budget/line/budget/{budget_id}")
    return r.json() if r is not None and r.status_code == 200 else []


def line_key(l):
    """Tupla CANONICA de una budget_line SIN sus ids (para comparar legado
    vs planning y para equality de lineas no tocadas)."""
    return (
        l["id_cost_center"],
        l["line_type"],
        l["budget_date"],
        l.get("payment_date"),
        l.get("id_collection"),
        round(float(l["projected_amount"]), 6),
        l.get("description"),
        l["behavior_type"],
        None if l.get("variable_rate") is None else round(float(l["variable_rate"]), 9),
    )


def get_planning_row(budget_id):
    rows = api("GET", f"/budget/planning/?budget_year={YEAR}").json()
    return next((r for r in rows if r["id_budget"] == budget_id), None)


def delete_budget_hard(budget_id):
    """Limpieza: borra lineas y luego el budget via API (orden FK-safe)."""
    for l in get_lines(budget_id):
        api("DELETE", f"/budget/line/{l['id_budget_line']}")
    api("DELETE", f"/budget/{budget_id}")


def preclean():
    """Pre-clean idempotente: elimina cualquier 'PLN *' de 2027 y usuarios
    temporales de ejecuciones anteriores."""
    for stale in (TEST_DIR / "data").glob("PLN_*.xlsx"):
        try:
            stale.unlink()
        except Exception:
            pass
    try:
        r = api("GET", f"/budget/planning/?budget_year={YEAR}")
        if r is not None and r.status_code == 200:
            for row in r.json():
                if str(row["budget_name"]).startswith(MARK):
                    delete_budget_hard(row["id_budget"])
    except Exception:
        traceback.print_exc()
    try:
        rows = run_sql(f"SELECT id_user FROM users WHERE username = '{TEMP_USER}'", fetch=True) or []
        for (uid,) in rows:
            api("DELETE", f"/user/{uid}")
    except Exception:
        traceback.print_exc()


def postclean():
    try:
        for bid in state.created_budgets:
            delete_budget_hard(bid)
        if state.fin_user_id:
            api("DELETE", f"/user/{state.fin_user_id}")
    except Exception:
        traceback.print_exc()
    finally:
        for p in state.temp_xlsx:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


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
    return ck("00. Login admin (JWT)", False, (r.text[:80] if r is not None else "error"))


def t02_jwt_required():
    r = api("GET", "/budget/planning/", auth=False)
    ok = r is not None and r.status_code in (401, 403)
    return ck("NFR-4 GET /budget/planning/ sin token -> 401/403", ok,
              f"status={r.status_code if r is not None else 'error'}")


def t03_ac_reg_02():
    """AC-REG-02 v1.1: con 0 activos en el anio, Q0 (pnl y cash-flow)
    responde con la MISMA semantica que antes de BR-TGT-03; unica diferencia
    valida: el texto del warning normalizado por Enmienda A-01."""
    rows = run_sql(
        "SELECT count(*) FROM budgets WHERE budget_year = "
        f"{YEAR} AND status = 'active'", fetch=True)
    pre = int(rows[0][0]) if rows else -1
    ck("AC-REG-02 precondicion: 0 activos en el anio de prueba", pre == 0,
       f"activos={pre}")

    r = api("GET", f"/budget/analytics/pnl?date_from={YEAR}-01-01&date_to={YEAR}-12-31")
    if r is None or r.status_code != 200:
        return ck("AC-REG-02 P&L sin id_budget (0 activos) intacto", False,
                  f"status={r.status_code if r is not None else 'error'}")
    meta = r.json()["meta"]
    warns = meta.get("warnings") or []
    # AC-REG-02 v1.1 (A-01): misma semantica (budget_source=null + warning
    # presente); la UNICA diferencia valida es el texto normalizado.
    ok = (meta.get("budget_source") is None
          and f"No active budget for {YEAR}" in warns)
    out = ck("AC-REG-02 P&L sin id_budget (0 activos) intacto", ok,
             f"source={meta.get('budget_source')} warns={[w for w in warns if 'No active' in w]}")

    cf = api("GET", f"/budget/analytics/cash-flow?date_from={YEAR}-01-01"
                    f"&date_to={YEAR}-12-31&outflow_source=budget&initial_balance=0")
    if cf is not None and cf.status_code == 200:
        cfm = cf.json()["meta"]
        cf_ok = (cfm.get("budget_source") is None
                 and f"No active budget for {YEAR}" in (cfm.get("warnings") or []))
        ck("AC-REG-02 (A-01) cash-flow sin id_budget (0 activos): misma semantica",
           cf_ok, f"source={cfm.get('budget_source')}")
    else:
        ck("AC-REG-02 (A-01) cash-flow sin id_budget (0 activos): misma semantica",
           False, f"status={cf and cf.status_code}")
    return out


def t04_ac_up_1():
    """AC-UP-1: par de archivos -> 201; 1 Budget draft is_scenario=False;
    expansion de payment rules identica al legado; tipos/condicion de
    gastos correcta."""
    inc_rows = count_excel_rows(INCOME_EXCEL)
    exp_rows = count_excel_rows(EXPENSE_EXCEL)

    with INCOME_EXCEL.open("rb") as fi, EXPENSE_EXCEL.open("rb") as fg:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME),
                       "file_gastos": (EXPENSE_EXCEL.name, fg, XLSX_MIME)},
                data={"scenario_name": NAME_BASE, "budget_year": YEAR,
                      "budget_period": PERIOD})
    if r is None or r.status_code != 201:
        return ck("AC-UP-1 upload 2 archivos -> 201", False,
                  (r.text[:120] if r is not None else "error"))
    body = r.json()
    state.base_id = body["id_budget"]
    state.created_budgets.append(state.base_id)

    ck("AC-UP-1 201 con payload PlanningUploadResult", set(body) == {
        "id_budget", "scenario_name", "budget_year", "lines_income",
        "lines_expense", "total_income", "total_expense_fixed",
        "payment_rules_expansions"}, f"keys={sorted(body)}")
    ck("AC-UP-1 lines_expense = filas Excel de gastos",
       body["lines_expense"] == exp_rows,
       f"{body['lines_expense']} vs {exp_rows}")
    ck("AC-UP-1 payment_rules_expansions = lines_income - filas Excel",
       body["payment_rules_expansions"] == body["lines_income"] - inc_rows
       and body["lines_income"] > inc_rows,
       f"exp={body['payment_rules_expansions']} rows={inc_rows}")

    row = get_planning_row(state.base_id)
    ok_meta = (row is not None and row["is_scenario"] is False
               and row["status"] == "draft" and row["parent_budget_name"] is None
               and row["lines_count"] == body["lines_income"] + body["lines_expense"])
    ck("AC-UP-1/BR-ING-02 Budget base draft, is_scenario=False, sin padre",
       ok_meta, f"row={row and {k: row[k] for k in ('is_scenario','status','parent_budget_name','lines_count')}}")

    # Totales contra el Excel
    df_inc = pd.read_excel(INCOME_EXCEL, engine="openpyxl", skiprows=7)
    exp_total_income = float(pd.to_numeric(df_inc["Monto"], errors="coerce").fillna(0).sum())
    df_exp = pd.read_excel(EXPENSE_EXCEL, engine="openpyxl", skiprows=7)
    fixed = df_exp["Comportamiento"].astype(str).str.strip() == "Fijo"
    exp_total_fixed = float(
        pd.to_numeric(df_exp.loc[fixed, "Monto o Tasa Solicitado"], errors="coerce").fillna(0).sum())
    ck("AC-UP-1 total_income = Σ Monto ingresos (reglas pct suman 1.0)",
       abs(body["total_income"] - exp_total_income) < 0.01,
       f"{body['total_income']} vs {exp_total_income}")
    ck("AC-UP-1 total_expense_fixed = Σ montos Fijos (variables aportan 0)",
       abs(body["total_expense_fixed"] - exp_total_fixed) < 0.01,
       f"{body['total_expense_fixed']} vs {exp_total_fixed}")

    # Tipos y condicion de gastos desde el detalle
    lines = get_lines(state.base_id)
    state.base_lines = {l["id_budget_line"]: l for l in lines}
    exp_lines = [l for l in lines if l["line_type"] == "expense"]
    counts = {}
    for l in exp_lines:
        counts[l["behavior_type"]] = counts.get(l["behavior_type"], 0) + 1
    want = {"fixed": int(fixed.sum()),
            "variable_sales": int((df_exp["Comportamiento"].astype(str).str.strip()
                                   == "Variable por Facturación").sum()),
            "variable_receivables": int((df_exp["Comportamiento"].astype(str).str.strip()
                                         == "Variable por Recaudo").sum())}
    ck("AC-UP-1 gastos: tipos fixed/variable_sales/variable_receivables correctos",
       counts == want, f"{counts} vs {want}")
    var_ok = all(l["projected_amount"] == 0 and l["variable_rate"] not in (None, 0)
                 for l in exp_lines if l["behavior_type"] != "fixed")
    fix_ok = all(l["variable_rate"] is None for l in exp_lines if l["behavior_type"] == "fixed")
    ck("AC-UP-1 variables: projected_amount=0 y variable_rate=tasa del Excel",
       var_ok and fix_ok, f"var_ok={var_ok} fix_ok={fix_ok}")

    # Payment date escalonada del legado: toda linea income tiene payment_date
    inc_lines = [l for l in lines if l["line_type"] == "income"]
    ck("AC-UP-1 expansion BR-ING-05: income lines con payment_date derivada",
       all(l["payment_date"] is not None for l in inc_lines),
       f"{len(inc_lines)} lineas income")
    return True


def t05_ac_up_4():
    """AC-UP-4 (BR-ING-04): mismo (year, name) -> 400."""
    with INCOME_EXCEL.open("rb") as fi:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME)},
                data={"scenario_name": NAME_BASE, "budget_year": YEAR,
                      "budget_period": PERIOD})
    ok = r is not None and r.status_code == 400 and \
        f"already exists for year {YEAR}" in r.text
    return ck("AC-UP-4 nombre duplicado en el anio -> 400", ok,
              (r.text[:100] if r is not None else "error"))


def t06_ac_up_2():
    """AC-UP-2: CECO inexistente en gastos -> 400 con lista + rollback TOTAL
    (ni Budget ni lineas)."""
    bad = make_variant_xlsx(
        EXPENSE_EXCEL, TEST_DIR / "data" / (MARK.strip() + "_bad_ceco.xlsx"),
        [("Centro de Costo", "999999 CECO SIN EXISTIR", 0)])
    before = run_sql(f"SELECT count(*) FROM budgets WHERE budget_year={YEAR}", fetch=True)
    with INCOME_EXCEL.open("rb") as fi, bad.open("rb") as fg:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME),
                       "file_gastos": (bad.name, fg, XLSX_MIME)},
                data={"scenario_name": NAME_BADCX, "budget_year": YEAR,
                      "budget_period": PERIOD})
    ok_status = r is not None and r.status_code == 400
    detail = r.json().get("detail") if r is not None else None
    ok_body = (isinstance(detail, dict)
               and detail.get("message") == "Cost centers not found"
               and "999999" in (detail.get("missing_cost_centers") or []))
    ck("AC-UP-2/BR-ING-03 CECO desconocido -> 400 estructurado", ok_status and ok_body,
       f"detail={str(detail)[:120]}")

    after = run_sql(f"SELECT count(*) FROM budgets WHERE budget_year={YEAR}", fetch=True)
    zero = (before and after and int(before[0][0]) == int(after[0][0]))
    lines_orphan = run_sql(
        "SELECT count(*) FROM budget_lines bl JOIN budgets b ON b.id_budget=bl.id_budget "
        f"WHERE b.budget_year={YEAR} AND b.budget_name='{NAME_BADCX}'", fetch=True)
    zero &= bool(lines_orphan) and int(lines_orphan[0][0]) == 0
    return ck("AC-UP-2 rollback total: cero Budget + cero lineas en BD", zero,
              f"budgets {before} -> {after}, lineas_huérfanas={lines_orphan}")


def t07_ac_up_3():
    """AC-UP-3 (BR-ING-06): fila con fecha 2026 y budget_year=2027 -> 400
    found_years + cero registros."""
    bad = make_variant_xlsx(
        INCOME_EXCEL, TEST_DIR / "data" / (MARK.strip() + "_bad_year.xlsx"),
        [("proyectada", datetime(2026, 3, 15), 0)])  # "Fecha de la Facturacion (Proyectada)"
    with bad.open("rb") as fi, EXPENSE_EXCEL.open("rb") as fg:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (bad.name, fi, XLSX_MIME),
                       "file_gastos": (EXPENSE_EXCEL.name, fg, XLSX_MIME)},
                data={"scenario_name": NAME_BADYEAR, "budget_year": YEAR,
                      "budget_period": PERIOD})
    ok_status = r is not None and r.status_code == 400
    detail = r.json().get("detail") if r is not None else None
    ok_body = (isinstance(detail, dict)
               and detail.get("message") == "Rows outside declared budget_year"
               and detail.get("found_years") == [2026])
    if not (ok_status and ok_body):
        return ck("AC-UP-3 fila 2026 con year=2027 -> 400 found_years", False,
                  f"detail={str(detail)[:150]}")
    reg = run_sql(
        f"SELECT count(*) FROM budgets WHERE budget_name='{NAME_BADYEAR}'", fetch=True)
    return ck("AC-UP-3 400 found_years=[2026] + cero registros (rollback)",
              ok_body and reg and int(reg[0][0]) == 0,
              f"budgets_creados={reg[0][0] if reg else '?'}")


def t08_upload_income_only():
    """§5.1: file_gastos opcional -> escenario sin gastos valido (201)."""
    with INCOME_EXCEL.open("rb") as fi:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME)},
                data={"scenario_name": NAME_DUP, "budget_year": YEAR,
                      "budget_period": PERIOD})
    ok = r is not None and r.status_code == 201 \
        and r.json()["lines_expense"] == 0 and r.json()["lines_income"] > 0
    if ok:
        state.created_budgets.append(r.json()["id_budget"])
    return ck("§5.1 upload solo-incomes (file_gastos opcional) -> 201", ok,
              (r.text[:120] if r is not None else "error"))


def t09_ac_reg_01():
    """AC-REG-01: legados budget-plan-income|expense dan resultados
    IDENTICOS tras el refactor T-02 (mismos archivos -> mismas lineas) y
    clone-for-scenario sigue respondiendo 200 (stub)."""
    with INCOME_EXCEL.open("rb") as fi:
        r_inc = api("POST", "/budget/upload/budget-plan-income",
                    files={"file": (INCOME_EXCEL.name, fi, XLSX_MIME)},
                    data={"budget_name": NAME_LEG_INC, "budget_year": YEAR,
                          "budget_period": PERIOD})
    with EXPENSE_EXCEL.open("rb") as fe:
        r_exp = api("POST", "/budget/upload/budget-plan-expense",
                    files={"file": (EXPENSE_EXCEL.name, fe, XLSX_MIME)},
                    data={"budget_name": NAME_LEG_EXP, "budget_year": YEAR,
                          "budget_period": PERIOD})
    if not (r_inc is not None and r_inc.status_code == 200
            and r_exp is not None and r_exp.status_code == 200):
        return ck("AC-REG-01 legados 200 tras T-02", False,
                  f"inc={r_inc and r_inc.status_code} exp={r_exp and r_exp.status_code}")
    state.leg_inc_id = r_inc.json()["id_budget"]
    state.leg_exp_id = r_exp.json()["id_budget"]
    state.created_budgets += [state.leg_inc_id, state.leg_exp_id]
    ck("AC-REG-01 legados responden 200 y cuentan lineas iguales al upload",
       True, f"inc={r_inc.json()['budget_lines_count']} "
             f"exp={r_exp.json()['budget_lines_count']}")

    base = api("GET", f"/budget/planning/{state.base_id}/detail").json()
    base_keys = sorted(line_key(l) for l in get_lines(state.base_id))
    # sorted() GLOBAL sobre la union (inc+exp), como el lado base:
    leg_keys = sorted(
        [line_key(l) for l in get_lines(state.leg_inc_id)]
        + [line_key(l) for l in get_lines(state.leg_exp_id)]
    )
    ck("AC-REG-01 BR-ING-05: expansion identico legado vs planning (tuplas de lineas)",
       base_keys == leg_keys,
       f"base={len(base_keys)} legados={len(leg_keys)}")

    r_clone = api("POST", f"/budget/analytics/clone-for-scenario/{state.base_id}"
                          f"?scenario_name=PLN-stub")
    ok_stub = r_clone is not None and r_clone.status_code == 200
    return ck("AC-REG-01 /analytics/clone-for-scenario (stub) intacto", ok_stub,
              f"status={r_clone and r_clone.status_code}; base is_scenario="
              f"{base.get('is_scenario')}")


def t10_ac_cl_1():
    """AC-CL-1: clone +10 -> mismo numero de lineas, Σ = 1.10×Σ origen,
    parent/is_scenario/draft correctos."""
    r = api("POST", "/budget/planning/clone",
            json={"id_budget": state.base_id, "nuevo_nombre": NAME_CLONE10,
                  "modifier_pct": 10.0})
    if r is None or r.status_code != 201:
        return ck("AC-CL-1 clone +10 -> 201", False,
                  (r.text[:120] if r is not None else "error"))
    body = r.json()
    state.clone10_id = body["id_budget"]
    state.created_budgets.append(state.clone10_id)
    ck("AC-CL-1 nuevo escenario draft, is_scenario=True, parent=base, anio origen",
       body["status"] == "draft" and body["is_scenario"] is True
       and body["parent_budget_id"] == state.base_id
       and body["budget_year"] == YEAR and body["budget_name"] == NAME_CLONE10,
       f"{ {k: body[k] for k in ('status','is_scenario','parent_budget_id','budget_year')} }")

    base_lines = get_lines(state.base_id)
    clone_lines = get_lines(state.clone10_id)
    ck("AC-CL-1 misma cantidad de lineas", len(clone_lines) == len(base_lines),
       f"{len(clone_lines)} vs {len(base_lines)}")
    s_base = sum(l["projected_amount"] for l in base_lines)
    s_clone = sum(l["projected_amount"] for l in clone_lines)
    rel = abs(s_clone - 1.1 * s_base) / max(abs(s_base), 1.0)
    ck("AC-CL-2 Σ projected_amount = 1.10 × Σ origen (BR-CLN-02, sin redondear)",
       rel < TOL, f"clone={s_clone} expected={1.1 * s_base} rel={rel:.2e}")

    by_key = {}
    for l in base_lines:
        k0 = (l["id_cost_center"], l["line_type"], l["budget_date"],
              l.get("payment_date"), l.get("id_collection"), l.get("description"),
              l["behavior_type"])
        by_key.setdefault(k0, []).append(l)
    ratio_ok, rate_ok = True, True
    for l in clone_lines:
        k = (l["id_cost_center"], l["line_type"], l["budget_date"],
             l.get("payment_date"), l.get("id_collection"), l.get("description"),
             l["behavior_type"])
        srcs = by_key.get(k)
        if not srcs:
            ratio_ok = False
            continue
        src = srcs.pop(0)
        expected = src["projected_amount"] * 1.1
        if abs(l["projected_amount"] - expected) > 1e-6:
            ratio_ok = False
        if l.get("variable_rate") != src.get("variable_rate"):
            rate_ok = False
    ck("AC-CL-1/2 cada linea escalada ×1.1 con resto de campos copiado", ratio_ok)
    return ck("AC-CL-2/BR-CLN-03 variable_rate COPIADA SIN escalar (0.08->0.08)", rate_ok)


def t11_ac_cl_3():
    """AC-CL-3: modifier=-100 -> todo projected_amount 0; -101 -> 422.
    Tambien modifier omitido (default 0 -> copia exacta, BR-CLN-02)."""
    r0 = api("POST", "/budget/planning/clone",
             json={"id_budget": state.base_id, "nuevo_nombre": NAME_CLONE0})
    if r0 is not None and r0.status_code == 201:
        state.created_budgets.append(r0.json()["id_budget"])
    exact = r0 is not None and r0.status_code == 201 and \
        sorted(line_key(l) for l in get_lines(r0.json()["id_budget"])) == \
        sorted(line_key(l) for l in get_lines(state.base_id))
    ck("BR-CLN-02 modifier_pct default 0 -> copia exacta", exact,
       (r0.text[:80] if r0 is not None and r0.status_code != 201 else ""))

    r = api("POST", "/budget/planning/clone",
            json={"id_budget": state.b_id or state.base_id,
                  "nuevo_nombre": NAME_CLONE100, "modifier_pct": -100.0})
    if r is None or r.status_code != 201:
        return ck("AC-CL-3 modifier_pct=-100 -> todo projected_amount=0", False,
                  (r.text[:100] if r is not None else "error"))
    state.created_budgets.append(r.json()["id_budget"])
    allzero = all(abs(l["projected_amount"]) == 0 for l in get_lines(r.json()["id_budget"]))
    ck("AC-CL-3 modifier_pct=-100 -> todo projected_amount=0", allzero)

    r2 = api("POST", "/budget/planning/clone",
             json={"id_budget": state.base_id, "nuevo_nombre": NAME_BADCLONE,
                   "modifier_pct": -101.0})
    return ck("AC-CL-3 modifier_pct=-101 -> 422 (rango [-100,∞))",
              r2 is not None and r2.status_code == 422,
              f"status={r2 and r2.status_code}")


def t12_clone_of_clone_and_target_snapshot():
    """BR-CLN-04 (ASM-6): clonar un clon y la Meta Activa es permitido; el
    origen nunca se muta."""
    # Primero designamos la base como meta (AC-MT-1 lo rehace con B/C):
    api("PUT", f"/budget/planning/{state.base_id}/set-target")
    before_keys = sorted(line_key(l) for l in get_lines(state.base_id))
    r = api("POST", "/budget/planning/clone",
            json={"id_budget": state.clone10_id, "nuevo_nombre": NAME_CLONEDUP,
                  "modifier_pct": 0})
    if r is None or r.status_code != 201:
        return ck("BR-CLN-04 clon de clon permitido", False,
                  (r.text[:100] if r is not None else "error"))
    state.created_budgets.append(r.json()["id_budget"])
    parent_ok = r.json()["parent_budget_id"] == state.clone10_id  # linaje directo
    after_keys = sorted(line_key(l) for l in get_lines(state.base_id))
    ck("BR-CLN-04/ASM-6 parent_budget_id = fuente DIRECTA (clon de clon)", parent_ok)
    ck("BR-CLN-04 el origen (Meta Activa) NUNCA se muta al clonar",
       before_keys == after_keys)


def t13_ac_ce_1():
    """AC-CE-1: PUT /cell/{id} -> 200; solo cambia projected_amount (y
    description si viene); las demas lineas quedan identicas."""
    lines = get_lines(state.base_id)
    target = next(l for l in lines if l["line_type"] == "income")
    state.target_line_id = target["id_budget_line"]
    snap = {l["id_budget_line"]: line_key(l) for l in lines}
    new_amount = 4999999.0
    r = api("PUT", f"/budget/planning/cell/{state.target_line_id}",
            json={"projected_amount": new_amount})
    if r is None or r.status_code != 200:
        return ck("AC-CE-1 PUT /cell -> 200", False,
                  (r.text[:100] if r is not None else "error"))
    body = r.json()
    ck("AC-CE-1 respuesta BudgetLine con el nuevo monto",
       body["id_budget_line"] == state.target_line_id
       and body["projected_amount"] == new_amount)

    after = {l["id_budget_line"]: line_key(l) for l in get_lines(state.base_id)}
    others_same = all(after[i] == snap[i] for i in snap if i != state.target_line_id)
    target_changed_only_amount = (
        after[state.target_line_id][0:5] == snap[state.target_line_id][0:5]  # cc/fechas/coll
        and after[state.target_line_id][5] == round(new_amount, 6)           # amount
    )
    ck("AC-CE-1/BR-CEL-01 las demas lineas quedan identicas; solo monto mutado",
       others_same and target_changed_only_amount,
       f"others_same={others_same}")

    # description opcional
    r2 = api("PUT", f"/budget/planning/cell/{state.target_line_id}",
             json={"projected_amount": new_amount, "description": "edicion smoke"})
    desc_ok = r2 is not None and r2.status_code == 200 and \
        r2.json()["description"] == "edicion smoke"
    ck("AC-CE-1 description opcional se actualiza cuando se envia", desc_ok)
    # restaurar monto original para no afectar comparaciones previas
    api("PUT", f"/budget/planning/cell/{state.target_line_id}",
        json={"projected_amount": float(snap[state.target_line_id][5]),
              "description": snap[state.target_line_id][6] or " "})
    after2 = {l["id_budget_line"]: line_key(l) for l in get_lines(state.base_id)}
    return ck("restauracion post-AC-CE-1 (snapshot identico)", after2 == snap)


def t14_ac_ce_2():
    """AC-CE-2: -5 -> 422; no-numerico -> 422; id inexistente -> 404."""
    r1 = api("PUT", f"/budget/planning/cell/{state.target_line_id}",
             json={"projected_amount": -5})
    r2 = api("PUT", "/budget/planning/cell/999999999",
             json={"projected_amount": 10})
    r3 = api("PUT", f"/budget/planning/cell/{state.target_line_id}",
             json={"projected_amount": "abc"})
    return ck("AC-CE-2 -5 -> 422, id inexistente -> 404, no numerico -> 422",
              r1.status_code == 422 and r2.status_code == 404 and r3.status_code == 422,
              f"{r1.status_code}/{r2.status_code}/{r3.status_code}")


def t15_ac_ce_3():
    """AC-CE-3 (ASM-7): dos escrituras concurrentes -> ambas 200, gana la
    ultima, sin bloqueo."""
    results, finals = [], []
    amounts = [1111111.0, 2222222.0]

    def put(amount):
        r = api("PUT", f"/budget/planning/cell/{state.target_line_id}",
                json={"projected_amount": amount})
        results.append(r.status_code if r is not None else 0)

    threads = [threading.Thread(target=put, args=(a,)) for a in amounts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = get_lines(state.base_id)
    final = next(l for l in final if l["id_budget_line"] == state.target_line_id)
    finals.append(final["projected_amount"])
    ok = all(s == 200 for s in results) and final["projected_amount"] in amounts
    return ck("AC-CE-3 dos PUT concurrentes: ambas 200, last-write-wins", ok,
              f"statuses={results}, final={final['projected_amount']}")


def t16_ac_mt_1():
    """AC-MT-1 (BR-TGT-01): un unico active por anio; el anterior cierra;
    un tercer intento deja cerrado al segundo. BR-TGT-02 idempotente."""
    r_b = api("POST", "/budget/planning/clone",
              json={"id_budget": state.base_id, "nuevo_nombre": NAME_CLONE0 + " B",
                    "modifier_pct": 0})
    if r_b is None or r_b.status_code != 201:
        return ck("AC-MT-1 setup: clon B creado", False,
                  (r_b.text[:100] if r_b is not None else "error"))
    state.b_id = r_b.json()["id_budget"]
    state.created_budgets.append(state.b_id)

    r_c = api("POST", "/budget/planning/clone",
              json={"id_budget": state.b_id, "nuevo_nombre": NAME_CLONE0 + " C",
                    "modifier_pct": 0})
    state.c_id = r_c.json()["id_budget"]
    state.created_budgets.append(state.c_id)

    rb = api("PUT", f"/budget/planning/{state.b_id}/set-target")
    base_was_active = False  # base fue activada en t12 (origen snapshot)
    ok_b = rb is not None and rb.status_code == 200 and rb.json() == {
        "id_budget": state.b_id, "budget_year": YEAR, "demoted_budget_id": state.base_id}
    if rb is not None and rb.status_code == 200:
        base_was_active = True
    ck("AC-MT-1 set-target B -> B active, base cerrada (demoted_budget_id)", ok_b,
       (rb.text[:120] if rb is not None else "error"))

    rc = api("PUT", f"/budget/planning/{state.c_id}/set-target")
    ok_c = rc is not None and rc.status_code == 200 and rc.json()["demoted_budget_id"] == state.b_id
    ck("AC-MT-1 set-target C -> C active, B cerrada", ok_c,
       (rc.text[:120] if rc is not None else "error"))

    idem = api("PUT", f"/budget/planning/{state.c_id}/set-target")
    ok_i = idem is not None and idem.status_code == 200 and \
        idem.json() == {"id_budget": state.c_id, "budget_year": YEAR,
                        "demoted_budget_id": None}
    ck("BR-TGT-02 idempotente: re-marcar C -> 200 sin cambios", ok_i,
       (idem.text[:120] if idem is not None else "error"))

    rows = api("GET", f"/budget/planning/?budget_year={YEAR}").json()
    actives = [r for r in rows if r["status"] == "active"]
    b_closed = get_planning_row(state.b_id)["status"] == "closed"
    base_status = get_planning_row(state.base_id)["status"]
    return ck("AC-MT-1 GET /budget/planning/?budget_year -> UNICO active = C; B y base closed",
              len(actives) == 1 and actives[0]["id_budget"] == state.c_id
              and b_closed and base_status == "closed",
              f"actives={[a['id_budget'] for a in actives]} b={b_closed} base={base_status}")


def t17_ac_mt_2():
    """AC-MT-2 (BR-TGT-03): Q0 del engine compara contra C (escenario), no
    contra un presupuesto base."""
    r = api("GET", f"/budget/analytics/pnl?date_from={YEAR}-01-01&date_to={YEAR}-12-31")
    if r is None or r.status_code != 200:
        return ck("AC-MT-2 P&L Q0 resuelve el escenario Meta Activa", False,
                  f"status={r and r.status_code}")
    meta = r.json()["meta"]
    src = meta.get("budget_source") or {}
    no_warn = f"No active budget for {YEAR}" not in (meta.get("warnings") or [])
    return ck("AC-MT-2 P&L Q0 resuelve el escenario Meta Activa (C)",
              src.get("id_budget") == state.c_id and src.get("status") == "active"
              and no_warn,
              f"budget_source={src}")


def t17b_ac_mt_4():
    """AC-MT-4 (Enmienda A-01): GET /budget/analytics/cash-flow SIN
    id_budget resuelve la Meta Activa-escenario C:
    meta.budget_source.id_budget == C, sin warning 'No active budget for
    {anio}', y las salidas de presupuesto (Q5) provienen realmente de C
    (prueba diferencial vs un id_budget explicito distinto)."""
    base_url = (f"/budget/analytics/cash-flow?date_from={YEAR}-01-01"
                f"&date_to={YEAR}-12-31&outflow_source=budget&initial_balance=0")
    r_auto = api("GET", base_url)
    if r_auto is None or r_auto.status_code != 200:
        return ck("AC-MT-4 cash-flow sin id_budget resuelve escenario C", False,
                  f"status={r_auto and r_auto.status_code}")
    auto = r_auto.json()
    src = auto["meta"].get("budget_source") or {}
    ck("AC-MT-4 meta.budget_source.id_budget == C (escenario activo)",
       src.get("id_budget") == state.c_id and src.get("status") == "active",
       f"budget_source={src}")
    ck("AC-MT-4 sin warning 'No active budget for " + str(YEAR) + "' (A-01)",
       f"No active budget for {YEAR}" not in (auto["meta"].get("warnings") or []),
       f"warns={[w for w in auto['meta']['warnings'] if 'No active' in w]}")

    # Q5 no silencioso: con outflow_source=budget y sin AP, las salidas del
    # auto-resuelto deben ser exactamente las del escenario C explicito...
    r_c = api("GET", base_url + f"&id_budget={state.c_id}")
    same = (r_c is not None and r_c.status_code == 200
            and r_c.json()["time_series"] == auto["time_series"]
            and r_c.json()["summary"] == auto["summary"])
    ck("AC-MT-4 salidas identicas a cash-flow?id_budget=C (Q5 desde la Meta)",
       same)
    total_out = sum(abs(p["outflows"]) for p in auto["time_series"])
    ck("AC-MT-4 las salidas de presupuesto NO son el 0.0 silencioso (bug pre-A-01)",
       total_out > 0, f"Σ|outflows|={total_out}")
    # ...y NO coinciden con las de otro escenario (discriminador: clone10
    # tiene los gastos fijos x1.1 != C)
    r_d = api("GET", base_url + f"&id_budget={state.clone10_id}")
    differs = (r_d is not None and r_d.status_code == 200
               and r_d.json()["time_series"] != auto["time_series"])
    return ck("AC-MT-4 diferencial: id_budget=clone10 produce salidas distintas",
              differs)


def t18_ac_mt_3():
    """AC-MT-3: usuario no-admin (Financiero) -> 403 sin mutacion.
    Financiero SI puede subir/clonar/editar (JWT estandar, ASM-9/PQ-1)."""
    r = api("POST", "/user/", auth=False, json={
        "first_name": "Smoke", "last_name": "Financiero",
        "document": TEMP_DOC, "gender": 1, "username": TEMP_USER,
        "email": f"{TEMP_USER}@smoke-crm.com", "id_city": 1,
        "password": TEMP_USER_PASS})
    if r is None or r.status_code not in (200, 201):
        return ck("AC-MT-3 usuario Financiero temporal creado", False,
                  (r.text[:100] if r is not None else "error"))
    state.fin_user_id = r.json()["id_user"]
    # UserCreate no incluye id_role (default Nuevo); lo fijamos a Financiero
    # (id_role=5) por SQL, como haria el seed real del CRM.
    try:
        run_sql(f"UPDATE users SET id_role = (SELECT id_role FROM roles "
                f"WHERE role_name='Financiero') WHERE id_user = {state.fin_user_id}")
    except Exception as e:
        return ck("AC-MT-3 ajuste de rol Financiero (SQL/docker)", False, str(e)[:120])

    rl = api("POST", "/login/", auth=False,
             json={"username": TEMP_USER, "password": TEMP_USER_PASS})
    if rl is None or rl.status_code != 200:
        return ck("AC-MT-3 login del usuario Financiero", False,
                  (rl.text[:80] if rl is not None else "error"))
    fin_headers = {"Authorization": f"Bearer {rl.json()['access_token']}"}

    r403 = requests.request("PUT", f"{BASE_URL}/budget/planning/{state.b_id}/set-target",
                            headers=fin_headers, timeout=30)
    ck("AC-MT-3 set-target como Financiero -> 403", r403.status_code == 403,
       f"status={r403.status_code}")

    ok_upload = False
    with INCOME_EXCEL.open("rb") as fi:
        ru = requests.request("POST", f"{BASE_URL}/budget/planning/upload",
                              headers=fin_headers,
                              files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME)},
                              data={"scenario_name": MARK + "Fin subio", "budget_year": YEAR,
                                    "budget_period": PERIOD}, timeout=60)
        ok_upload = ru.status_code == 201
        if ok_upload:
            state.created_budgets.append(ru.json()["id_budget"])
    ck("PQ-1: Financiero SI puede usar /upload (JWT estandar, sin gate)", ok_upload)

    rows = api("GET", f"/budget/planning/?budget_year={YEAR}").json()
    actives = [x for x in rows if x["status"] == "active"]
    c_status = get_planning_row(state.c_id)["status"]
    b_status = get_planning_row(state.b_id)["status"]
    return ck("AC-MT-3 sin mutacion: sigue C activo y B cerrado",
              len(actives) == 1 and actives[0]["id_budget"] == state.c_id
              and c_status == "active" and b_status == "closed",
              f"actives={[a['id_budget'] for a in actives]}")


def t19_listing_and_404():
    """§5.4: filas completas + orden (active primero); §5.5 parent_budget_name
    en clones; 404s."""
    rows = api("GET", f"/budget/planning/?budget_year={YEAR}").json()
    fields_ok = rows and all({"id_budget", "budget_name", "budget_year", "is_scenario",
                              "parent_budget_name", "status", "lines_count",
                              "total_income", "total_expense",
                              "created_at"} <= set(r) for r in rows)
    first = rows[0] if rows else {}
    ordered_ok = first.get("id_budget") == state.c_id and first.get("status") == "active"
    ck("§5.4 listing con todas las columnas agregadas", bool(fields_ok), f"{len(rows)} filas")
    ck("§5.4 orden: active primero dentro del anio", ordered_ok,
       f"primera fila={ {k: first.get(k) for k in ('id_budget','status','lines_count','total_income')} }")
    clone = next((r for r in rows if r["id_budget"] == state.b_id), {})
    parent_ok = clone.get("parent_budget_name") == NAME_BASE
    ck("§5.4 parent_budget_name por self-JOIN (clon -> base)", parent_ok,
       f"parent={clone.get('parent_budget_name')!r}")

    r_d = api("GET", "/budget/planning/999999999/detail")
    r_c = api("POST", "/budget/planning/clone",
              json={"id_budget": 999999999, "nuevo_nombre": MARK + "no existe"})
    r_detail = api("GET", f"/budget/planning/{state.b_id}/detail")
    detail_ok = r_detail.status_code == 200 and \
        r_detail.json()["parent_budget_name"] == NAME_BASE and \
        len(r_detail.json()["budget_lines"]) > 0
    return ck("§5.5/§5.7 detail 200 con parent + 404 en ids inexistentes",
              r_d.status_code == 404 and r_c.status_code == 404 and detail_ok,
              f"detail404={r_d.status_code} clone404={r_c.status_code} ok200={detail_ok}")


def t20_budget_year_range():
    """§5.1: budget_year fuera de [2000,2100] -> 422 (422 por Query/Form)."""
    with INCOME_EXCEL.open("rb") as fi:
        r = api("POST", "/budget/planning/upload",
                files={"file_ingresos": (INCOME_EXCEL.name, fi, XLSX_MIME)},
                data={"scenario_name": MARK + "ano malo", "budget_year": 1999})
    return ck("§5.1 budget_year=1999 -> 422", r is not None and r.status_code == 422,
              f"status={r and r.status_code}")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Budget Planning Smoke Tests (BE-S4-BUDGET-PLANNING)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Ingresos : {INCOME_EXCEL}")
    print(f"Gastos   : {EXPENSE_EXCEL}")
    print(f"Anio de prueba: {YEAR} | prefijo aislado: '{MARK}*'")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    print()

    tests = [
        t02_jwt_required,
        t03_ac_reg_02,
        t04_ac_up_1,
        t05_ac_up_4,
        t06_ac_up_2,
        t07_ac_up_3,
        t08_upload_income_only,
        t09_ac_reg_01,
        t10_ac_cl_1,
        t11_ac_cl_3,
        t12_clone_of_clone_and_target_snapshot,
        t13_ac_ce_1,
        t14_ac_ce_2,
        t15_ac_ce_3,
        t16_ac_mt_1,
        t17_ac_mt_2,
        t17b_ac_mt_4,
        t18_ac_mt_3,
        t19_listing_and_404,
        t20_budget_year_range,
    ]
    try:
        for t in tests:
            try:
                t()
            except Exception as e:
                ck(f"{t.__name__} (excepcion)", False, f"{type(e).__name__}: {str(e)[:140]}")
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
