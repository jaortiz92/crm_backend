"""
Budget PURCHASE Lines Smoke Tests (BE-S8-BUDGET-PURCHASES)

Spec: crm_backend/spec/backend.02_18_Spec_Backend_budgets_purchases.md
§9 + §10 (AMENDMENT A-01: real SIIGO imports template with Temporada).
Patrón de los smokes existentes (test_budget_planning_lines_smoke.py /
test_budget_planning_smoke.py): corre contra el backend dev real
(:8003), JWT de .env_test, SQL de apoyo por psycopg2 (fallback docker
exec psql, con NULL-SENTINEL -P para distinguir NULL de '' real).

Cubre:
    AC-BE8-1  POST purchase: 201, DB guarda 'PURCHASE' (NAME), payment_date
               NULL forzado en silencio (BR-PUR-03), detail lo devuelve como
               "purchase"; behavior variable_sales / variable_rate -> 400
               {"reason": NUEVO literal A-01 "purchase lines must be fixed
               with no variable rate"}
    AC-BE8a-2 POST purchase CON id_collection VALIDO (temporada) -> 201
               persistida con temporada (A-01 §10.2, la compra admite
               season como ingreso); id inexistente -> 404 "Collection {id}
               not found" (la validacion de existencia sigue vigente)
    AC-BE8-2/3 PUT de una compra: payment_date -> 400 detalle literal
               {"reason": "payment dates of a purchase derive from the
               line's payable terms"}; variable_rate -> 400 con el motivo
               de forma NUEVO; id_collection AHORA PERMITIDO: valido ->
               200 con temporada cambiada, inexistente -> 404 (AC-BE8a-3);
               budget_date sigue editable (año validado BR-LINE-04)
    AC-BE8-3  Regresión: purchase NO suma a total_income/total_expense del
               listing (CASE sums intactos) y una compra no puede arrastrar
               como origin "line" (guard BR-CO-12 verificado en AC-BE8-5)
    AC-BE8a-1 Upload del FIXTURE REAL del stakeholder (Formato Solicitud
               Presupuesto Importaciones.xlsx, hoja 1 "Requisición de
               Facturación" leida por POSICION, header en FILA 8 ->
               skiprows=7, segunda hoja "Tablas" ignorada) como
               file_compras de un escenario 2026 NUEVO (con el ingreso 2026
               de test/data, sin gastos): 201 con lines_purchase/
               total_purchase y la compra persistida con id_collection
               RESUELTO por Temporada "KAV26" (paridad ingreso, NO
               bloqueante: una fila con temporada desconocida -> NULL);
               payment_date NULL y budget_date = FECHA DE IMPORTACION
               (no la fecha de solicitud)
    AC-BE8-4  Upload con 3 archivos (file_compras layout real A-01:
               Centro de Costo | Fecha Importacion | Temporada | Monto):
               income+expense+purchase en una transaccion; CECO desconocido
               SOLO en compras -> 400 missing_cost_centers + rollback TOTAL;
               fecha de importacion en anio distinto -> 400 found_years
    AC-BE8a-4 Faltan columnas obligatorias (Temporada/Monto) -> 400
               missing_columns; celda de fecha vacia o Monto negativo ->
               400 invalid_rows con row = FILA EXCEL REAL (header fila 8
               => idx + 9, antes +2)
     AC-BE8-5  Fuente N-1 (2096) con compra en CECO comprador (terminos
                60/90/120 @ .34/.33/.33, importacion 15/12) + ingreso del
                mismo CECO + ingreso de CECO NO comprador + compra "dirty"
                anclada en N sin terminos + flag ON en N (2097): payload
                EXACTO (orden BR-CO-10 extendido {line:0, cogs:1, purchase:2}),
                cuotas origin "purchase" presentes, derivacion "cogs" del
                CECO comprador AUSENTE (switch D-4'), CECO no comprador
                conserva su "cogs", la compra anclada en N jamas aparece
                como origin "line" (BR-CO-12) y sin terminos => cuota unica
                100 % en la fecha de importacion (D-S7-4 mirror). Escenario
                SIN compras (2094->2095) => payload sin origin "purchase"
                alguno (NFR-BE8-3)
     AC-BE8b-1 Enmienda A-02 (spec §11, regla D-4': switch por LÍNEA): el
                mismo bloque 2096->2097 replica el caso real 266 con los
                CECOS y fechas REALES (compra 000001 25M 30/01, compra
                000002 18M 30/05; ingresos zonales 000101/000201 de Kyly y
                000202/000302 de Tinta anclados en dic-2096): la compra en
                un CECO de la Línea L APAGA la derivacion cogs de TODOS los
                CECOS de L (cero dobles en el payload EXACTO), un CECO de
                otra Línea (100) conserva el suyo, y las compras 30/01 y
                30/05 no generan filas en N (cuotas dentro de N-1). Se
                anade ademas una seccion UNIT in-process (importa
                app.crud.budget.planning contra la misma BD dev) que
                compara get_carryover_cogs_lines SIN claves (comportamiento
                pre-A-02: los 4 cecos zonales SI derivaban cogs = la doble
                cuenta reportada) vs CON claves D-4' (cero)
     AC-BE8b-2 CECO SIN id_line: compra solo en 998801 => la clave cc:
                switcha ESE CECO y nada mas; centinela 998802 (sin compra)
                no se ve afectado (check del set exacto de
                get_purchasing_source_keys; a nivel payload, un ingreso sin
                linea jamas genera cuota 2097 — ancla D-S7-4 — por lo que
                la señal es el set de claves + payload exacto invariante)
     AC-BE8b-3 Fuente sin compras => claves (∅,∅) => payload byte-identico
                a A-01 (check unitario del set vacio sobre 2094 + lista
                exacta del par centinela 2094->2095 de NFR-BE8-3)
     NFR-BE8-2  (medido in-process con eventos SQLAlchemy de la misma
                sesion): build_carryover_payload_lines = 5 queries sin
                compras (BE-S7 + claves) y 6 con compras; +2 maximo sobre
                BE-S7 independientemente del # de filas
     AC-BE8-6  POST /clone escala las compras con el modifier (BR-CLN-02
                generico) y NO copia behavior distinto de fixed

Banco de pruebas de AC-BE8-1/2a/2/3/6: clon draft del presupuesto 69 (año
2025) creado por API y ELIMINADO con DELETE /budget/{id} (delete-draft) al
final, mas clon x1.2 del clon (la compra "temporada valida" de AC-BE8a-2
se BORRA dentro del propio test: el banco queda en exactamente 2 compras
para no mover los contadores de AC-BE8-3/6). Datos centinela de
AC-BE8-4/a-1/a-4/5/b: anos 2094-2097 (sin datos historicos), uploads 2027 y
el fixture 2026, todos prefijo de nombre "PURC " (+ CECOs desechables
'998801'/'998802' sin id_line + tasas globales temporales 'SMOKE BE8 %'
para que la derivacion COGS sea determinista en los anos centinela). Las
compras/ingresos de AC-BE8b-1 usan los CECOS REALES del escenario 266
(000001/000002, 000101/000201, 000202/000302) SOLO en modo lectura sobre
el escenario centinela 2096 (nunca se toca el 266; su carryover esta OFF).
La seccion unit requiere el venv del backend (sqlalchemy+deps) y exporta
env vars sintetizadas de app.settings ANTES de importar app. Pre-clean y
post-clean GARANTIZADOS (try/finally) con verificacion de 0 restos.

Uso:
    1. docker compose -f docker-compose-dev.yaml up   (backend :8003)
    2. test/.env_test con USERNAME/PASSWORD
    3. python test/test_budget_purchases_smoke.py     (desde crm_backend/)
       — la seccion unit t11c exige el interprete con las deps del backend
       (venv_backend/Scripts/python.exe o equivalente: sqlalchemy, fastapi,
       pydantic-settings, psycopg2), porque importa app.crud en el proceso
       con env vars sintetizadas hacia la BD dev de .env_test
"""

import sys
import traceback
from datetime import date, timedelta
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

PG_HOST = _cfg("PG_HOST", "127.0.0.1")
PG_PORT = int(_cfg("PG_PORT", "5433"))
PG_USER = _cfg("PG_USER") or dev_config.get("POSTGRES_USER", "postgres")
PG_PASSWORD = _cfg("PG_PASSWORD") or dev_config.get("POSTGRES_PASSWORD", "")
PG_DB = _cfg("PG_DB") or dev_config.get("POSTGRES_DB", "crm")
PG_DOCKER = _cfg("PG_DOCKER_CONTAINER", "db_crm_dev")

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

INCOME_EXCEL = TEST_DIR / "data" / "Formato Solicitud Presupuesto Ingresos.xlsx"
EXPENSE_EXCEL = TEST_DIR / "data" / "Formato Solicitud Presupuesto Gastos.xlsx"
# AC-BE8a-1: el FIXTURE REAL entregado por el stakeholder (layout SIIGO con
# header en fila 8 y Temporada) y el ingreso SIIGO 2026 (el fixture de
# compras proyecta fecha de importacion 2026-08-01 => escenario 2026).
PURCHASE_FIXTURE_2026 = (TEST_DIR / "data"
                         / "Formato Solicitud Presupuesto Importaciones.xlsx")
INCOME_2026_EXCEL = (TEST_DIR / "data"
                     / "Formato Solicitud Presupuesto Ingresos 2026.xlsx")
for p in (INCOME_EXCEL, EXPENSE_EXCEL, PURCHASE_FIXTURE_2026,
          INCOME_2026_EXCEL):
    if not p.exists():
        print(f"ERROR: falta el archivo Excel {p}")
        sys.exit(1)

# ══════════════════════════════════════════════════════════════
# CONSTANTES DEL TEST
# ══════════════════════════════════════════════════════════════

MARK = "PURC "         # prefijo de aislamiento de nombres
SRC_YEAR = 2096        # N-1 de la fuente con compras (ano centinela)
TGT_YEAR = 2097        # N del escenario con flag ON
NOSRC_YEAR = 2094      # fuente del par de regresion SIN compras
NOTGT_YEAR = 2095
UP_YEAR = 2027         # los xlsx SIIGO de test/data proyectan 2027
FIX_YEAR = 2026        # anio del fixture real de compras (import. 01/08/2026)
BENCH_69_YEAR = 2025   # anio real del presupuesto 69 (banco de pruebas)
TOL = 1e-6

# Literal NUEVO de la Enmienda A-01 (backend.02_18 §10.2). El viejo
# pre-A-01 era "purchase lines must be fixed with no collection and no
# variable rate" (la temporada ya NO esta prohibida en compras).
PURCHASE_SHAPE_REASON = (
    "purchase lines must be fixed with no variable rate"
)
# Literal VIGENTE (no cambio con A-01): guard de payment_date en PUT.
PURCHASE_PAYMENT_REASON = (
    "payment dates of a purchase derive from the line's payable terms"
)
XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet")

state = type("S", (), {})()
state.headers = {}
state.token = None
state.clone_id = None       # clon draft del 69 (banco AC-BE8-1/2/3/6)
state.clone2_id = None      # clon x1.2 del clon (AC-BE8-6)
state.pur_line = None       # compra creada via API sobre el clon
state.src_id = None         # escenario 2096 con compras
state.tgt_id = None         # escenario 2097 flag ON
state.nosrc_id = None       # escenario 2094 sin compras
state.notgt_id = None       # escenario 2095 flag ON
state.cc_buyer = None       # CECO con terminos 60/90/120 (line 1)
state.cc_other = None       # CECO no comprador con terminos +30 (line 100)
state.cc_exp = None         # CECO del gasto material (line 100)
state.cc_null = None        # CECO desechable SIN id_line (sin terminos)
state.cc_null2 = None       # 2o CECO SIN id_line: centinela b-2 SIN compra
state.cc266 = {}            # codigos reales del 266 (code -> id) AC-BE8b-1
state.lines266 = {}         # codigos del 266 -> id_line (verificacion setup)
state.coll_real = None      # id_collection de "KAV26" (catalogo dev)
state.coll_alt = None       # id_collection alterno para el PUT (temporada)
state.rate_ids = []         # tasas globales temporales 2094/2096
state.upload_ids = []       # budgets creados por /upload en AC-BE8-4/a-1
state.total = 0
state.passed = 0
state.failed = 0
state.results = []


# ══════════════════════════════════════════════════════════════
# UTILIDADES (mismos patrones de los smokes 02_12/02_13)
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
    import subprocess
    # -P null=@NULL@: sin psycopg2 el fallback psql -tA imprimia NULL como
    # cadena VACIA (indistinguible de '' legitimo) y checks tipo
    # `payment_date is None` fallaban en el host. Con el centinela se
    # mapea NULL -> None, replicando el comportamiento de psycopg2.
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


def raw_line(line_id):
    rows = run_sql(
        "SELECT line_type, payment_date, behavior_type, projected_amount, "
        f"id_collection FROM budget_lines WHERE id_budget_line={line_id}",
        fetch=True)
    return rows[0] if rows else None


def planning_row(budget_id, year):
    r = api("GET", f"/budget/planning/?budget_year={year}")
    if r is None or r.status_code != 200:
        return None
    return next((row for row in r.json() if row["id_budget"] == budget_id), None)


# Columnas del layout REAL (A-01 §10.1): encabezados en fila 8 del xlsx.
# Nombre del Colaborador y Fecha de Solicitud se toleran y el parser las
# IGNORA (fecha de SOLICITUD != fecha de IMPORTACION).
PUR_XLSX_COLS = ["Centro de Costo", "Nombre del Colaborador",
                 "Fecha de Solicitud", "Fecha Importacion", "Temporada",
                 "Monto", "Descripcion"]


def make_purchases_xlsx(rows, drop_cols=()):
    """BytesIO del layout REAL (BE-S8 A-01 §10.1): primera hoja leida por
    POSICION con 7 filas de relleno -> encabezados en FILA 8 (skiprows=7)
    y datos desde la fila 9 (offset invalid_rows = idx + 9).
    rows = lista de (Centro de Costo, Fecha Importacion, Temporada, Monto,
    Descripcion); drop_cols = encabezados a eliminar (test missing_columns)."""
    cols = [c for c in PUR_XLSX_COLS if c not in drop_cols]
    data = []
    for cc, fimp, temporada, monto, desc in rows:
        full = {"Centro de Costo": cc, "Nombre del Colaborador": "Smoke",
                "Fecha de Solicitud": None, "Fecha Importacion": fimp,
                "Temporada": temporada, "Monto": monto, "Descripcion": desc}
        data.append([full[c] for c in cols])
    buf = BytesIO()
    df = pd.DataFrame(data, columns=cols)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # startrow=7 (0-indexed) => el header cae en la FILA EXCEL 8, en
        # par con los SIIGO reales de ingresos/gastos.
        df.to_excel(writer, index=False, startrow=7,
                    sheet_name="Requisición de Facturación")
    buf.seek(0)
    return buf


def upload3(name, compras_buf=None, bad_compras_name=None, year=UP_YEAR,
            with_expense=True):
    """POST /budget/planning/upload con income+expense SIIGO reales y el
    tercer archivo opcional de compras (None = flujo de dos archivos)."""
    files = {"file_ingresos": (INCOME_EXCEL.name, INCOME_EXCEL.open("rb"),
                               XLSX_MIME)}
    if with_expense:
        files["file_gastos"] = (EXPENSE_EXCEL.name, EXPENSE_EXCEL.open("rb"),
                                XLSX_MIME)
    if compras_buf is not None:
        files["file_compras"] = (bad_compras_name or "compras.xlsx",
                                 compras_buf, XLSX_MIME)
    r = api("POST", "/budget/planning/upload", files=files,
            data={"scenario_name": name, "budget_year": year,
                  "budget_period": "ANUAL"})
    for key in ("file_ingresos", "file_gastos"):
        if key in files:
            files[key][1].close()
    return r


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
        if (d1, o1, c1) != (d2, o2, c2) or abs(a1 - a2) > 0.01:
            return False
    return True


# ══════════════════════════════════════════════════════════════
# LIMPIEZA (pre/post garantizados)
# ══════════════════════════════════════════════════════════════

SENTINELS = (SRC_YEAR, TGT_YEAR, NOSRC_YEAR, NOTGT_YEAR)


def sweep():
    # lineas + budgets centinela (2094-2097) y cualquier 'PURC *' de otros
    # anos (clones del 69 en 2025, uploads de 2027) — orden FK-safe.
    years = ",".join(str(y) for y in SENTINELS)
    run_sql("DELETE FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_year IN ({years}))")
    run_sql("DELETE FROM budget_lines WHERE id_budget IN "
            f"(SELECT id_budget FROM budgets WHERE budget_name LIKE '{MARK}%')")
    run_sql(f"DELETE FROM budgets WHERE budget_year IN ({years})")
    run_sql(f"DELETE FROM budgets WHERE budget_name LIKE '{MARK}%'")
    # CECOs desechables sin id_line (codes fijos, idempotente)
    run_sql("DELETE FROM budget_lines WHERE id_cost_center IN "
            "(SELECT id_cost_center FROM cost_centers "
            " WHERE cost_center_code IN ('998801','998802'))")
    run_sql("DELETE FROM cost_centers WHERE cost_center_code IN "
            "('998801','998802')")
    # tasas globales temporales de la derivacion COGS centinela
    run_sql("DELETE FROM line_cost_rates WHERE rate_name LIKE 'SMOKE BE8%'")


def preclean():
    try:
        sweep()
    except Exception:
        traceback.print_exc()


def postclean():
    try:
        sweep()
        rest_b = int(sql_scalar(
            "SELECT count(*) FROM budgets WHERE budget_name LIKE "
            f"'{MARK}%' OR budget_year IN ({','.join(map(str, SENTINELS))})"))
        rest_l = int(sql_scalar(
            "SELECT count(*) FROM budget_lines WHERE id_budget IN "
            "(SELECT id_budget FROM budgets WHERE budget_year IN "
            f"({','.join(map(str, SENTINELS))}) "
            "UNION SELECT id_budget FROM budgets WHERE budget_name LIKE "
            f"'{MARK}%')"))
        rest_cc = int(sql_scalar(
            "SELECT count(*) FROM cost_centers WHERE cost_center_code IN "
            "('998801','998802')"))
        rest_r = int(sql_scalar(
            "SELECT count(*) FROM line_cost_rates WHERE rate_name LIKE "
            "'SMOKE BE8%'"))
        return ck("Limpieza garantizada: 0 restos (budgets/lineas/CECO/tasas)",
                  rest_b == 0 and rest_l == 0 and rest_cc == 0 and rest_r == 0,
                  f"budgets={rest_b} lineas={rest_l} ceco={rest_cc} tasas={rest_r}")
    except Exception:
        traceback.print_exc()
        return False


# ══════════════════════════════════════════════════════════════
# PRUEBAS — banco de pruebas: clon draft del presupuesto 69 (2025)
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


def t02_clone_bench():
    """POST /clone sobre el 69 -> banco draft 2025 (BR-CLN-04 fuente
    inmutable); se elimina con delete-draft al final."""
    r = api("POST", "/budget/planning/clone",
            json={"id_budget": 69, "nuevo_nombre": MARK + "be8-bench",
                  "modifier_pct": 0})
    if r is None or r.status_code != 201:
        return ck("Setup: clon draft del presupuesto 69 -> 201", False,
                  (r.text[:120] if r is not None else "error"))
    state.clone_id = r.json()["id_budget"]
    ck("Setup: clon draft del presupuesto 69 -> 201",
       r.json()["status"] == "draft" and r.json()["budget_year"] == BENCH_69_YEAR,
       f"id={state.clone_id}")
    state.cc_buyer = int(sql_scalar(
        "SELECT cc.id_cost_center FROM cost_centers cc "
        "JOIN line_payable_terms t ON t.id_line = cc.id_line "
        "GROUP BY cc.id_cost_center HAVING count(*) >= 3 "
        "ORDER BY cc.id_cost_center LIMIT 1"))
    state.cc_other = int(sql_scalar(
        "SELECT cc.id_cost_center FROM cost_centers cc "
        "JOIN line_payable_terms t ON t.id_line = cc.id_line "
        f"WHERE t.payment_days = 30 AND t.payment_pct = 1 "
        f"AND cc.id_cost_center <> {state.cc_buyer} "
        # A-02: el control "otra Linea" debe estar OBLIGATORIAMENTE en una
        # Linea DISTINTA a la del comprador (por-CECO ambas cosas casaban
        # aqui; con el switch por-Linea un mismo id_line romperia t11).
        f"AND cc.id_line <> (SELECT id_line FROM cost_centers "
        f"WHERE id_cost_center = {state.cc_buyer}) "
        "ORDER BY cc.id_cost_center LIMIT 1"))
    state.cc_exp = state.cc_other
    state.cc_null = int(sql_scalar(
        "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
        "cost_center_name, is_active, description) VALUES "
        "((SELECT max(id_cost_center) + 1 FROM cost_centers), '998801', "
        "'SMOKE BE8 no-line', true, "
        "'BE-S8 smoke: CECO sin id_line (cuota unica D-S7-4)') "
        "RETURNING id_cost_center"))
    # AC-BE8b-2: SEGUNDO CECO sin id_line, centinela que NO tiene compra —
    # la clave cc: del comprador debe switchar solo a si mismo (998801),
    # nunca al 998802 (dos CECOs sin linea jamas se switchan entre si).
    state.cc_null2 = int(sql_scalar(
        "INSERT INTO cost_centers (id_cost_center, cost_center_code, "
        "cost_center_name, is_active, description) VALUES "
        "((SELECT max(id_cost_center) + 1 FROM cost_centers), '998802', "
        "'SMOKE BE8 no-line 2', true, "
        "'BE-S8 A-02 smoke: 2o CECO sin id_line (control cc: exacto)') "
        "RETURNING id_cost_center"))
    # NB: id explicito — la secuencia cost_centers_id_cost_center_seq de la
    # dev esta desincronizada (seed historico con ids fijos; last_value=1),
    # dejar que nextval la colisionaria. No se toca la secuencia: fuera de
    # alcance del smoke.
    # Temporadas reales del catalogo dev: KAV26 es la del FIXTURE A-01;
    # la alterna se usa para el PUT (AC-BE8a-3) y NO debe coincidir.
    state.coll_real = int(sql_scalar(
        "SELECT id_collection FROM collections "
        "WHERE short_collection_name = 'KAV26'"))
    state.coll_alt = int(sql_scalar(
        "SELECT min(id_collection) FROM collections "
        f"WHERE short_collection_name <> 'KAV26' AND id_collection > 0"))
    ck("Setup: CECOs de fixture (comprador con >=2 terminos, "
       "no-comprador en OTRA Linea, 2 sin-line) + temporadas KAV26/alterna",
       bool(state.cc_buyer) and bool(state.cc_other)
       and bool(state.cc_null) and bool(state.cc_null2)
       and bool(state.coll_real) and bool(state.coll_alt)
       and state.coll_real != state.coll_alt,
       f"buyer={state.cc_buyer} other={state.cc_other} "
       f"null={state.cc_null}/{state.cc_null2} coll={state.coll_real}/"
       f"{state.coll_alt}")
    # ── AC-BE8b-1 (A-02, spec §11): los CECOS REALES del defecto 266.
    # El comercio compra en "Facturación {Línea}" (000001 Kyly / 000002
    # Tinta) y vende en los CECOS ZONALES de ESA MISMA Línea (000101/
    # 000201 Kyly, 000202/000302 Tinta) — el switch por-CECO nunca casaba
    # (comprador != vendedor) y pagaba doble. Se usan SOLO en lectura: la
    # semilla va al escenario centinela 2096, el 266 real no se toca.
    for code in ("000001", "000002", "000101", "000201", "000202", "000302"):
        row = run_sql(
            "SELECT id_cost_center, id_line FROM cost_centers "
            f"WHERE cost_center_code = '{code}'", fetch=True)
        if not row or row[0][1] is None:
            return ck("Setup: los 6 CECOS reales del 266 existen y tienen "
                      "id_line", False, f"problema con codigo {code}")
        state.cc266[code] = int(row[0][0])
        state.lines266[code] = int(row[0][1])
    state.line_buyer = int(sql_scalar(
        f"SELECT id_line FROM cost_centers WHERE id_cost_center="
        f"{state.cc_buyer}"))
    state.line_other = int(sql_scalar(
        f"SELECT id_line FROM cost_centers WHERE id_cost_center="
        f"{state.cc_other}"))
    kyly, tinta = state.lines266["000001"], state.lines266["000002"]
    return ck("Setup AC-BE8b-1: identidad de Lineas del 266 (zonal Kyly == "
              "Linea de 000001, zonal Tinta == Linea de 000002, Kyly != "
              "Tinta, Linea control fuera de ambas)",
              state.lines266["000101"] == state.lines266["000201"] == kyly
              and state.lines266["000202"] == state.lines266["000302"]
              == tinta and kyly != tinta
              and state.line_other not in (kyly, tinta),
              f"cc={state.cc266} lines={state.lines266} "
              f"buyer_line={state.line_buyer} other_line={state.line_other}")


def _post_line(body, budget=None):
    return api("POST", f"/budget/planning/{budget or state.clone_id}/line",
               json=body)


def t03_ac_be8_1_create():
    """AC-BE8-1: purchase valida -> 201 + 'PURCHASE' en DB + payment NULL +
    detail 'purchase'; payment_date enviado -> forzado NULL (BR-PUR-03)."""
    r = _post_line({
        "id_cost_center": state.cc_buyer, "line_type": "purchase",
        "budget_date": "2025-04-10", "projected_amount": 8_000_000.0,
        "description": "AC-BE8-1 compra",
    })
    if r is None or r.status_code != 201:
        return ck("AC-BE8-1 POST purchase -> 201", False,
                  (r.text[:150] if r is not None else "error"))
    body = r.json()
    state.pur_line = body["id_budget_line"]
    ck("AC-BE8-1 201/respuesta: line_type 'purchase', behavior 'fixed', "
       "payment_date null",
       body["line_type"] == "purchase" and body["behavior_type"] == "fixed"
       and body["payment_date"] is None
       and body["projected_amount"] == 8_000_000.0)
    raw = raw_line(state.pur_line)
    ck("AC-BE8-1 DB cruda: line_type='PURCHASE' (NAME), payment_date NULL",
       raw is not None and raw[0] == "PURCHASE" and raw[1] is None
       and raw[2] == "FIXED" and float(raw[3]) == 8_000_000.0,
       f"raw={raw}")
    fresh = detail_line(state.clone_id, state.pur_line)
    ck("AC-BE8-1 GET .../detail devuelve la compra como 'purchase'",
       fresh is not None and fresh["line_type"] == "purchase")
    # BR-PUR-03: payment_date ENVIADO -> NULL en silencio (201, sin error)
    r2 = _post_line({
        "id_cost_center": state.cc_other, "line_type": "purchase",
        "budget_date": "2025-05-10", "payment_date": "2025-11-30",
        "projected_amount": 1_000_000.0, "description": "BR-PUR-03",
    })
    ok_null = (r2 is not None and r2.status_code == 201
               and r2.json()["payment_date"] is None
               and raw_line(r2.json()["id_budget_line"])[1] is None)
    if r2 is not None and r2.status_code == 201:
        state.pur_null = r2.json()["id_budget_line"]
    return ck("AC-BE8-1/BR-PUR-03 payment_date enviado -> 201 con NULL "
              "forzado en silencio", ok_null,
              (r2.text[:120] if r2 is not None else "error"))


def t04_ac_be8_1_guards():
    """AC-BE8-1/BR-PUR-02 (A-01 §10.2): solo behavior!=fixed | variable_rate
    -> 400 {"reason": NUEVO literal}. AC-BE8a-2: id_collection VALIDO ->
    201 con temporada persistida (se borra la fila para dejar el banco en
    2 compras); id_collection INEXISTENTE -> 404 "Collection {id} not
    found" (la validacion de existencia sigue vigente para compras)."""
    base = {"id_cost_center": state.cc_buyer, "line_type": "purchase",
            "budget_date": "2025-06-01", "projected_amount": 500_000.0}
    r1 = _post_line({**base, "behavior_type": "variable_sales",
                     "variable_rate": 0.5})
    ok1 = (r1 is not None and r1.status_code == 400
           and (r1.json().get("detail") or {}).get("reason")
           == PURCHASE_SHAPE_REASON)
    r3 = _post_line({**base, "variable_rate": 0.25})
    ok3 = (r3 is not None and r3.status_code == 400
           and (r3.json().get("detail") or {}).get("reason")
           == PURCHASE_SHAPE_REASON)
    ck("BR-PUR-02 (A-01) purchase+variable_sales -> 400 {reason} literal "
       "NUEVO", ok1, (r1.text[:130] if r1 is not None else "error"))
    ck("BR-PUR-02 (A-01) purchase+variable_rate -> 400 {reason} literal "
       "NUEVO", ok3, (r3.text[:130] if r3 is not None else "error"))

    # AC-BE8a-2: temporada VALIDA en compra -> 201 + id_collection
    # persistido (paridad ingreso). La fila se elimina enseguida via
    # DELETE /line para que el banco siga teniendo exactamente 2 compras
    # (AC-BE8-3/6 cuentan sobre el clon).
    rv = _post_line({**base, "id_collection": state.coll_real,
                     "description": "AC-BE8a-2 compra con temporada"})
    okv = False
    if rv is not None and rv.status_code == 201:
        vb = rv.json()
        raw_v = raw_line(vb["id_budget_line"])
        okv = (vb["id_collection"] == state.coll_real
               and vb["payment_date"] is None
               and raw_v is not None and raw_v[0] == "PURCHASE"
               and str(raw_v[4]) == str(state.coll_real))
        rd = api("DELETE", f"/budget/planning/line/{vb['id_budget_line']}")
        okv = okv and rd is not None and rd.status_code == 200
    ck("AC-BE8a-2 purchase con id_collection VALIDO -> 201 temporada "
       "persistida + fila de prueba borrada (banco intacto)", okv,
       (rv.text[:130] if rv is not None else "error"))
    rn = _post_line({**base, "id_collection": 999999})
    okn = (rn is not None and rn.status_code == 404
           and rn.json().get("detail") == "Collection 999999 not found")
    ck("AC-BE8a-2 purchase con id_collection INEXISTENTE -> 404 "
       "\"Collection 999999 not found\" (existe-check vigente)", okn,
       (rn.text[:120] if rn is not None else "error"))
    # validaciones preexistentes intactas sobre purchase:
    r4 = _post_line({**base, "budget_date": "2024-06-01"})
    ok4 = (r4 is not None and r4.status_code == 400
           and "does not match scenario year 2025" in r4.text)
    r5 = _post_line({**base, "id_cost_center": 999999})
    ok5 = (r5 is not None and r5.status_code == 404
           and r5.json().get("detail") == "Cost center 999999 not found")
    ck("BR-LINE-04 compra con budget_date 2024 en escenario 2025 -> 400 "
       "año exacto", ok4, (r4.text[:120] if r4 is not None else "error"))
    return ck("BR-LINE-02 compra con CECO inexistente -> 404 (FKs intactas)",
              ok5, (r5.text[:120] if r5 is not None else "error"))


def t05_ac_be8_2_update_guards():
    """AC-BE8-2: PUT de compra — payment_date 400 literal VIGENTE;
    variable_rate 400 forma (literal NUEVO A-01); budget_date editable con
    check de anio; PUT /cell sigue operando (genericidad). AC-BE8a-3:
    id_collection AHORA PERMITIDO — valido -> 200 con temporada cambiada,
    inexistente -> 404 (existe-check vigente)."""
    lid = state.pur_line
    r1 = api("PUT", f"/budget/planning/line/{lid}",
             json={"payment_date": "2025-09-01"})
    ok1 = (r1 is not None and r1.status_code == 400
           and (r1.json().get("detail") or {}).get("reason")
           == PURCHASE_PAYMENT_REASON)
    r1b = api("PUT", f"/budget/planning/line/{lid}",
              json={"payment_date": None})
    ok1b = (r1b is not None and r1b.status_code == 400
            and (r1b.json().get("detail") or {}).get("reason")
            == PURCHASE_PAYMENT_REASON)
    r2 = api("PUT", f"/budget/planning/line/{lid}",
             json={"variable_rate": 0.1})
    ok2 = (r2 is not None and r2.status_code == 400
           and (r2.json().get("detail") or {}).get("reason")
           == PURCHASE_SHAPE_REASON)
    ck("AC-BE8-2 PUT purchase payment_date -> 400 detalle literal §5.1-2 "
       "(vigente, no cambio con A-01)", ok1,
       (r1.text[:140] if r1 is not None else "error"))
    ck("BR-PUR-04 payment_date:null (present-but-null cuenta como enviado) "
       "-> 400", ok1b)
    ck("BR-PUR-04 (A-01) PUT variable_rate en compra -> 400 {reason} forma "
       "con literal NUEVO (no el mensaje generico de fixed)", ok2,
       (r2.text[:140] if r2 is not None else "error"))
    # AC-BE8a-3: PUT id_collection VALIDO -> 200 + temporada cambiada en
    # DB; INEXISTENTE -> 404. El payment_date NULL de la compra es
    # invariante intocada (se re-verifica tras el change de temporada).
    rv = api("PUT", f"/budget/planning/line/{lid}",
             json={"id_collection": state.coll_alt})
    ok_season = False
    if rv is not None and rv.status_code == 200:
        vb = rv.json()
        raw_v = raw_line(lid)
        ok_season = (vb["id_collection"] == state.coll_alt
                     and raw_v is not None and str(raw_v[4]) == str(state.coll_alt)
                     and raw_v[1] is None and vb["line_type"] == "purchase")
    rn = api("PUT", f"/budget/planning/line/{lid}",
             json={"id_collection": 999999})
    ok_404 = (rn is not None and rn.status_code == 404
              and rn.json().get("detail") == "Collection 999999 not found")
    ck("AC-BE8a-3 PUT purchase id_collection VALIDO -> 200 temporada "
       "cambiada (payment_date sigue NULL) / INEXISTENTE -> 404",
       ok_season and ok_404,
       (f"valid={str(rv.text)[:90] if rv is not None else 'err'} "
        f"inv={str(rn.text)[:80] if rn is not None else 'err'}"))
    # budget_date editable con validacion de anio vigente (fecha de
    # importacion corregible)
    r4 = api("PUT", f"/budget/planning/line/{lid}",
             json={"budget_date": "2024-01-05"})
    ok4 = r4 is not None and r4.status_code == 400 and "does not match" in r4.text
    r5 = api("PUT", f"/budget/planning/line/{lid}",
             json={"budget_date": "2025-04-11", "projected_amount": 9_000_000.0,
                   "description": "AC-BE8-2 editada"})
    fresh = detail_line(state.clone_id, lid) if (
        r5 is not None and r5.status_code == 200) else None
    ok5 = (fresh is not None and fresh["budget_date"] == "2025-04-11"
           and fresh["projected_amount"] == 9_000_000.0
           and fresh["payment_date"] is None
           and fresh["line_type"] == "purchase")
    ck("BR-PUR-04 budget_date de compra editable -> 400 anio erroneo / "
       "200 con fecha+monto nuevos (line_type/payment inmutables)",
       ok4 and ok5, (r5.text[:120] if r5 is not None else "error"))
    r6 = api("PUT", f"/budget/planning/cell/{lid}",
             json={"projected_amount": 8_000_000.0})
    ok6 = r6 is not None and r6.status_code == 200
    state.pur_amount = 8_000_000.0
    return ck("PUT /cell sobre una compra sigue operando (genericidad, "
              "monto restaurado a 8M)", ok6, (r6.text[:100] if r6 is not None else ""))


def t06_ac_be8_3_listing_totals():
    """AC-BE8-3 (parte listing): las compras NO suman a total_income/
    total_expense (CASE sums exactos) pero si a lines_count."""
    row = planning_row(state.clone_id, BENCH_69_YEAR)
    src = planning_row(69, BENCH_69_YEAR)
    if row is None or src is None:
        return ck("AC-BE8-3 listing del clon legible", False)
    ok = (row["lines_count"] == src["lines_count"] + 2
          and abs(row["total_income"] - src["total_income"]) < 0.01
          and abs(row["total_expense"] - src["total_expense"]) < 0.01)
    return ck("AC-BE8-3 compra: +2 lines_count, total_income/total_expense "
              "IDENTICOS al origen (purchase fuera de los CASE sums)", ok,
              f"clone={ {k: row[k] for k in ('lines_count','total_income','total_expense')} } "
              f"src69={ {k: src[k] for k in ('lines_count','total_income','total_expense')} }")


def t07_ac_be8_6_clone_scaling():
    """AC-BE8-6: clonar el banco con +20 % escala TAMBIEN las compras
    (BR-CLN-02 generico) y la copia conserva FIXED/payment NULL/'PURCHASE'."""
    r = api("POST", "/budget/planning/clone",
            json={"id_budget": state.clone_id,
                  "nuevo_nombre": MARK + "be8-x120", "modifier_pct": 20.0})
    if r is None or r.status_code != 201:
        return ck("AC-BE8-6 clon x1.2 del banco -> 201", False,
                  (r.text[:120] if r is not None else "error"))
    state.clone2_id = r.json()["id_budget"]
    rows = run_sql(
        "SELECT projected_amount, behavior_type, payment_date, line_type "
        "FROM budget_lines WHERE id_budget="
        f"{state.clone2_id} AND line_type='PURCHASE'", fetch=True) or []
    expected = round(state.pur_amount * 1.2, 6)
    expected2 = 1_200_000.0  # la BR-PUR-03 de 1M x1.2
    scaled = sorted(float(x[0]) for x in rows)
    ok = (len(rows) == 2
          and abs(scaled[0] - expected2) < 0.01
          and abs(scaled[1] - expected) < 0.01
          and all(x[1] == "FIXED" and x[2] is None and x[3] == "PURCHASE"
                  for x in rows))
    return ck("AC-BE8-6/BR-CLN-02 las PURCHASE se escalan x1.2 (comportamien"
              "to FIXED y payment_date NULL en toda copia)", ok,
              f"rows={rows} expected={[expected2, expected]}")


# ══════════════════════════════════════════════════════════════
# PRUEBAS — AC-BE8-4/a-4/a-1 upload de compras (ano centinela 2027 real
# de los xlsx SIIGO + escenario 2026 del FIXTURE de la A-01, siempre
# 'PURC *' y borrado al final)
# ══════════════════════════════════════════════════════════════

def t08_ac_be8_4_upload3():
    """AC-BE8-4: income+expense+compras (layout REAL A-01) -> 201 con
    lines_purchase/total_purchase; una fila = una compra (sin expansion),
    payment NULL. AC-BE8a-1 (HTTP): la Temporada se resuelve con paridad
    ingreso — conocida -> id_collection, DESCONOCIDA -> NULL sin bloquear."""
    buf = make_purchases_xlsx([
        ("410100 Administrativo General", date(2027, 3, 10), "KV26",
         12_500_000, "Importacion A"),
        ("000101 Facturacion Costa Z1", "20/07/2027", "ZZZ-99-INEXISTENTE",
         7_000_000, None),
    ])
    r = upload3(MARK + "up3 2027", buf)
    if r is None or r.status_code != 201:
        return ck("AC-BE8-4 upload con 3 archivos -> 201", False,
                  (r.text[:200] if r is not None else "error"))
    body = r.json()
    state.upload_ids.append(body["id_budget"])
    ck("AC-BE8-4 201 con lines_purchase=2 (1 fila Excel = 1 compra, cero "
       "expansion) y total_purchase exacto",
       body["lines_purchase"] == 2
       and abs(body["total_purchase"] - 19_500_000.0) < 0.01
       and body["lines_income"] > 0,
       f"{ {k: body[k] for k in ('lines_income', 'lines_expense', 'lines_purchase', 'total_purchase')} }")
    rows = run_sql(
        "SELECT count(*), min(payment_date::text), max(line_type) "
        "FROM budget_lines WHERE id_budget="
        f"{body['id_budget']} AND line_type='PURCHASE'", fetch=True)
    ck("AC-BE8-4 persistencia: 2 filas 'PURCHASE' con payment_date NULL "
       "(psycopg2/psql directo)", rows and int(rows[0][0]) == 2
       and rows[0][1] in (None, "None"), f"agg={rows}")
    seasons = run_sql(
        "SELECT b.description, c.short_collection_name, "
        "b.id_collection IS NOT NULL FROM budget_lines b LEFT JOIN "
        "collections c ON c.id_collection = b.id_collection WHERE "
        f"b.id_budget={body['id_budget']} AND b.line_type='PURCHASE' "
        "ORDER BY b.budget_date", fetch=True) or []
    truthy = {True, "t", "True", "1"}
    return ck("AC-BE8a-1 (HTTP) Temporada paridad-ingreso en upload: "
              "'KV26' -> id_collection resuelto, 'ZZZ-99-INEXISTENTE' -> "
              "NULL SIN bloquear (201)",
              len(seasons) == 2
              and seasons[0][2] in truthy and seasons[0][1] == "KV26"
              and seasons[1][2] not in truthy and seasons[1][0] is None,
              f"seasons={seasons}")


def t09_ac_be8_4_rejections():
    """AC-BE8-4: rechazo all-or-nothing por el archivo de compras —
    missing_cost_centers y found_years. AC-BE8a-4: columna obligatoria
    ausente (layout A-01: centro/fecha_importacion/temporada/monto) -> 400
    missing_columns; celda invalida -> invalid_rows con la FILA EXCEL REAL
    (header fila 8 => idx + 9): fecha vacia y Monto negativo."""
    bad_cc = make_purchases_xlsx([
        ("410100 OK", date(2027, 3, 1), "KV26", 1_000_000, None),
        ("999999 NO EXISTE", date(2027, 4, 1), "KV26", 2_000_000, None)])
    r1 = upload3(MARK + "bad-ceco", bad_cc)
    d1 = (r1.json().get("detail") or {}) if r1 is not None else {}
    ok1 = (r1 is not None and r1.status_code == 400
           and d1.get("message") == "Cost centers not found"
           and "999999" in (d1.get("missing_cost_centers") or []))
    reg1 = int(sql_scalar(
        f"SELECT count(*) FROM budgets WHERE budget_name='{MARK}bad-ceco'"))
    ck("AC-BE8-4 CECO malo SOLO en compras -> 400 missing_cost_centers "
       "agregado a la lista unica", ok1, f"detail={str(d1)[:110]}")
    ck("AC-BE8-4 rollback TOTAL (cero budgets 'PURC bad-ceco')", reg1 == 0)

    bad_year = make_purchases_xlsx([
        ("410100 OK", "15/12/2026", "KV26", 5_000_000, "fecha de otro anio")])
    r2 = upload3(MARK + "bad-year", bad_year)
    d2 = (r2.json().get("detail") or {}) if r2 is not None else {}
    ok2 = (r2 is not None and r2.status_code == 400
           and d2.get("message") == "Rows outside declared budget_year"
           and d2.get("found_years") == [2026])
    reg2 = int(sql_scalar(
        f"SELECT count(*) FROM budgets WHERE budget_name='{MARK}bad-year'"))
    ck("AC-BE8-4 fecha de importacion 2026 con year=2027 -> 400 "
       f"found_years=[2026] + rollback ({reg2} registros)", ok2 and reg2 == 0,
       f"detail={str(d2)[:110]}")

    bad_value = make_purchases_xlsx([
        ("410100 OK", date(2027, 3, 1), "KV26", 1_000_000, None),
        ("410100 OK", date(2027, 3, 2), "KV26", -5, "negativo")])
    r3 = upload3(MARK + "bad-value", bad_value)
    d3 = (r3.json().get("detail") or {}) if r3 is not None else {}
    # 7 filas de relleno + header en la 8: la 2a fila de datos es la FILA
    # EXCEL 10 (idx 1 + 9) — offset A-01, antes era fila 3 (idx + 2).
    ok3 = (r3 is not None and r3.status_code == 400
           and any(e.get("row") == 10 and e.get("column") == "Monto"
                   and e.get("reason") == "negative"
                   for e in (d3.get("invalid_rows") or [])))
    ck("AC-BE8a-4/A-01 Monto negativo en fila Excel 10 (header fila 8 => "
       "idx+9) -> 400 invalid_rows con numero REAL de fila", ok3,
       f"detail={str(d3)[:130]}")

    empty_date = make_purchases_xlsx([
        ("410100 OK", date(2027, 3, 1), "KV26", 1_000_000, None),
        ("410100 OK", None, "KV26", 2_000_000, "sin fecha de importacion")])
    r3b = upload3(MARK + "empty-date", empty_date)
    d3b = (r3b.json().get("detail") or {}) if r3b is not None else {}
    ok3b = (r3b is not None and r3b.status_code == 400
            and any(e.get("row") == 10 and e.get("column")
                    == "Fecha Importacion"
                    and e.get("reason") == "unparseable"
                    for e in (d3b.get("invalid_rows") or [])))
    ck("AC-BE8a-4 celda de FECHA VACIA en la 2a fila de datos -> 400 "
       "invalid_rows row=10 (fila Excel real, +9)", ok3b,
       f"detail={str(d3b)[:130]}")

    no_season = make_purchases_xlsx(
        [("410100 OK", date(2027, 3, 1), "KV26", 1_000_000, None)],
        drop_cols=("Temporada",))
    r3c = upload3(MARK + "no-col", no_season)
    d3c = (r3c.json().get("detail") or {}) if r3c is not None else {}
    ok3c = (r3c is not None and r3c.status_code == 400
            and d3c.get("message")
            == "Purchases file is missing mandatory columns"
            and d3c.get("missing_columns") == ["temporada"])
    reg3c = int(sql_scalar(
        f"SELECT count(*) FROM budgets WHERE budget_name='{MARK}no-col'"))
    ck("AC-BE8a-4 columna obligatoria TEMPORADA ausente (layout A-01) -> "
       f"400 missing_columns=[temporada] + rollback ({reg3c} registros)",
       ok3c and reg3c == 0, f"detail={str(d3c)[:130]}")

    r4 = upload3(MARK + "up2 2027", None)  # dos archivos -> defaults
    if r4 is not None and r4.status_code == 201:
        state.upload_ids.append(r4.json()["id_budget"])
        ok4 = (r4.json()["lines_purchase"] == 0
               and r4.json()["total_purchase"] == 0.0)
    else:
        ok4 = False
    return ck("NFR-BE8-3 upload de 2 archivos sigue valido: lines_purchase=0, "
              "total_purchase=0.0 (defaults aditivos)", ok4,
              (r4.text[:110] if r4 is not None and r4.status_code != 201 else ""))


def t09b_ac_be8a1_real_fixture():
    """AC-BE8a-1 (HTTP end-to-end): subir el FIXTURE REAL del stakeholder
    ('Formato Solicitud Presupuesto Importaciones.xlsx': hoja 1 leida por
    posicion con header en FILA 8 + hoja 'Tablas' ignorada). El stakeholder
    actualizo el archivo a la forma del caso real 266: DOS filas
    (000001 30/01/2026 50M y 000002 30/05/2026 20M, ambas Temporada
    KAV26). Como file_compras de un escenario 2026 RECIEN CREADO (los
    ingresos del SIIGO 2026 de test/data; sin gastos). 201 +
    lines_purchase/total_purchase + las compras con id_collection = KAV26
    (si KAV26 NO existiera en el catalogo la subida TAMBIEN daria 201 con
    temporada NULL — caso no-bloqueante cubierto en t08), budget_date =
    fechas de IMPORTACION (no la fecha de solicitud 20/08) y payment_date
    NULL. Limpieza via delete-draft en t13 (+sweep)."""
    files = {
        "file_ingresos": (INCOME_2026_EXCEL.name, INCOME_2026_EXCEL.open("rb"),
                          XLSX_MIME),
        "file_compras": (PURCHASE_FIXTURE_2026.name,
                         PURCHASE_FIXTURE_2026.open("rb"), XLSX_MIME),
    }
    r = api("POST", "/budget/planning/upload", files=files,
            data={"scenario_name": MARK + "fixture 2026",
                  "budget_year": FIX_YEAR, "budget_period": "ANUAL"})
    files["file_ingresos"][1].close()
    files["file_compras"][1].close()
    if r is None or r.status_code != 201:
        return ck("AC-BE8a-1 upload del fixture real 2026 -> 201", False,
                  (r.text[:200] if r is not None else "error"))
    body = r.json()
    state.upload_ids.append(body["id_budget"])
    ck("AC-BE8a-1 201 del fixture real: lines_purchase=2 y total_purchase="
       "70.000.000 (una fila = una compra, cero expansion)",
       body["lines_purchase"] == 2
       and abs(body["total_purchase"] - 70_000_000.0) < 0.01
       and body["lines_income"] > 0
       and body["lines_expense"] == 0,
       f"{ {k: body[k] for k in ('lines_income', 'lines_expense', 'lines_purchase', 'total_purchase')} }")
    rows = run_sql(
        "SELECT line_type, budget_date::text, payment_date, id_collection, "
        "projected_amount, description FROM budget_lines WHERE "
        f"id_budget={body['id_budget']} AND line_type='PURCHASE' "
        "ORDER BY id_budget_line", fetch=True) or []
    coll_expected = str(state.coll_real)
    ok_persist = (
        len(rows) == 2
        and all(r_[0] == "PURCHASE" for r_ in rows)
        and rows[0][1] == "2026-01-30"            # importacion fila 1
        and abs(float(rows[0][4]) - 50_000_000.0) < 0.01
        and rows[1][1] == "2026-05-30"            # importacion fila 2
        and abs(float(rows[1][4]) - 20_000_000.0) < 0.01
        and all(r_[2] is None for r_ in rows)     # payment_date SIEMPRE NULL
        and all(str(r_[3]) == coll_expected for r_ in rows)  # KAV26 -> id
        and all(r_[5] is None for r_ in rows))    # Descripcion vacia -> None
    return ck("AC-BE8a-1 compras persistidas: PURCHASE + budget_date="
              "2026-01-30/2026-05-30 (import., no solicitud 20/08) + "
              "payment NULL + id_collection={} (Temporada KAV26 resuelta "
              "en ambas filas)".format(coll_expected),
              ok_persist, f"rows={rows}")


# ══════════════════════════════════════════════════════════════
# PRUEBAS — AC-BE8-5 arrastre purchase + switch D-4 (anos 2096/2097)
# ══════════════════════════════════════════════════════════════

def t10_seed_carryover():
    """Fixture SQL: tasas globales temporales (cogs_pct=50) para que la
    derivacion COGS sea determinista en 2094/2096; escenario fuente 2096
    con compra del CECO comprador (terminos leidos del catalogo), compra
    'dirty' anclada en 2097 sin terminos (BR-CO-12), ingreso del mismo
    CECO comprador (su derivacion cogs DEBE desaparecer por D-4/D-4'),
    ingreso de CECO en OTRA Linea (cogs intacto) y gasto material con
    pago en 2097; MAS el bloque A-02 (AC-BE8b-1/2): replica del defecto
    266 con los CECOS reales — compras en los "Facturacion" 000001/000002
    y en el sin-linea 998801, ingresos en los zonales de LA MISMA Linea
    (000101/000201 Kyly, 000202/000302 Tinta) y en el sin-linea
    centinela 998802; fuente gemela 2094 SIN compras (AC-BE8b-3);
    targets 2097/2095 con flag ON via API."""
    for y in (SRC_YEAR, NOSRC_YEAR):
        rr = api("POST", "/budget/line-cost-rate/", json={
            "id_line": None, "rate_name": f"SMOKE BE8 {y}",
            "cogs_pct": 50.0, "date_from": f"{y}-01-01",
            "date_to": f"{y}-12-31", "is_active": True})
        if rr is None or rr.status_code not in (200, 201):
            return ck(f"Setup: tasa global temporal {y} -> 200/201", False,
                      (rr.text[:120] if rr is not None else "error"))
        state.rate_ids.append(rr.json()["id_line_cost_rate"])
    # terminos reales de las lineas de los CECOs semilla
    state.buyer_terms = run_sql(
        "SELECT t.payment_days, t.payment_pct FROM line_payable_terms t "
        "JOIN cost_centers cc ON cc.id_line=t.id_line "
        f"WHERE cc.id_cost_center={state.cc_buyer} "
        "ORDER BY t.payment_days, t.id_line_payable_term", fetch=True) or []
    state.other_terms = run_sql(
        "SELECT t.payment_days, t.payment_pct FROM line_payable_terms t "
        "JOIN cost_centers cc ON cc.id_line=t.id_line "
        f"WHERE cc.id_cost_center={state.cc_other} "
        "ORDER BY t.payment_days, t.id_line_payable_term", fetch=True) or []
    if len(state.buyer_terms) < 2:
        return ck("Setup: el CECO comprador tiene >=2 terminos", False,
                  f"terms={state.buyer_terms}")

    state.src_id = insert_budget(MARK + "src 2096", SRC_YEAR, "draft")
    state.tgt_id = insert_budget(MARK + "tgt 2097", TGT_YEAR, "draft")
    state.nosrc_id = insert_budget(MARK + "nosrc 2094", NOSRC_YEAR, "draft")
    state.notgt_id = insert_budget(MARK + "notgt 2095", NOTGT_YEAR, "draft")

    # fuente 2096 (importacion 15/12: cuotas a +60/+90/+120 caen en 2097)
    insert_line(state.src_id, state.cc_buyer, "PURCHASE", "2096-12-15", None,
                20_000_000, "BE8 compra comprador")
    insert_line(state.src_id, state.cc_null, "PURCHASE", "2097-06-01", None,
                3_000_000, "BE8 compra dirty anclada en N")
    insert_line(state.src_id, state.cc_buyer, "INCOME", "2096-12-15",
                "2096-12-20", 10_000_000, "BE8 ingreso comprador")
    insert_line(state.src_id, state.cc_other, "INCOME", "2096-12-05",
                "2096-12-15", 10_000_000, "BE8 ingreso no-comprador")
    insert_line(state.src_id, state.cc_exp, "EXPENSE", "2096-12-20",
                "2097-02-13", 1_000_000, "BE8 gasto material en N")
    # ── AC-BE8b-1 (Enmienda A-02): replica el caso 266 con los CECOS,
    # montos y dias REALES del defecto, anclados al par centinela
    # 2096->2097. Las compras entran en los CECOS "Facturacion {Linea}"
    # (000001/000002) y los ingresos en los ZONALES de la MISMA Linea
    # (000101/000201 Kyly; 000202/000302 Tinta). Las fechas reales de
    # importacion (30/01 y 30/05) + terminos (+60/90/120 y +90) siguen
    # cayendo dentro de N-1: los 25M/18M APORTAN CERO filas 2097 y solo
    # ejercen de LLAVE sobre sus Lineas. Con el switch viejo por-CECO,
    # los cuatro ingresos zonales anclados en diciembre SI derivaban
    # cuotas cogs en 2097 (la doble cuenta reportada); bajo D-4' deben
    # estar TODOS ausentes — el payload exacto de t11, que no los
    # incluye, es el centinela.
    insert_line(state.src_id, state.cc266["000001"], "PURCHASE",
                "2096-01-30", None, 25_000_000, "BE8b-1 266 Fact. Kyly")
    insert_line(state.src_id, state.cc266["000002"], "PURCHASE",
                "2096-05-30", None, 18_000_000, "BE8b-1 266 Fact. Tinta")
    insert_line(state.src_id, state.cc266["000101"], "INCOME", "2096-12-05",
                "2096-12-15", 4_000_000, "BE8b-1 266 zona Costa Kyly")
    insert_line(state.src_id, state.cc266["000201"], "INCOME", "2096-12-10",
                "2096-12-20", 6_000_000, "BE8b-1 266 zona Antioquia Kyly")
    insert_line(state.src_id, state.cc266["000202"], "INCOME", "2096-12-10",
                "2096-12-20", 3_000_000, "BE8b-1 266 zona Antioquia Tinta")
    insert_line(state.src_id, state.cc266["000302"], "INCOME", "2096-12-15",
                "2096-12-25", 5_000_000, "BE8b-1 266 zona Tolima Tinta")
    # ── AC-BE8b-2: CECOS SIN id_line. El cc_null tiene compra (la "dirty"
    # de arriba) e ingreso propio; cc_null2 es el centinela SIN compra.
    # Un ingreso sin Linea jamas genera cuota 2097 (D-S7-4: pago unico en
    # su propia ancla N-1), asi que la senal del cc: exacto vive en el set
    # de claves (check unitario t11c) y en que el payload exacto NO cambia.
    insert_line(state.src_id, state.cc_null, "INCOME", "2096-12-08",
                "2096-12-18", 4_000_000, "BE8b-2 ingreso cc: comprador")
    insert_line(state.src_id, state.cc_null2, "INCOME", "2096-12-09",
                "2096-12-19", 2_000_000, "BE8b-2 ingreso cc: sin compra")
    # terminos de la Linea Tinta (266): espejo de la doble cuenta unitaria
    state.tinta_terms = run_sql(
        "SELECT t.payment_days, t.payment_pct FROM line_payable_terms t "
        "JOIN cost_centers cc ON cc.id_line=t.id_line "
        f"WHERE cc.id_cost_center={state.cc266['000002']} "
        "ORDER BY t.payment_days, t.id_line_payable_term", fetch=True) or []
    if not state.tinta_terms:
        return ck("Setup: la Linea Tinta del 266 tiene terminos", False)
    # fuente 2094 SIN compras (regresion NFR-BE8-3)
    insert_line(state.nosrc_id, state.cc_other, "INCOME", "2094-12-05",
                "2094-12-15", 10_000_000, "BE8 ingreso sin compras")
    insert_line(state.nosrc_id, state.cc_exp, "EXPENSE", "2094-12-20",
                "2095-01-10", 500_000, "BE8 gasto en N")
    for tgt in (state.tgt_id, state.notgt_id):
        rf = api("PUT", f"/budget/planning/{tgt}/carryover",
                 json={"include_carryover": True})
        if rf is None or rf.status_code != 200:
            return ck(f"Setup: flag ON en {tgt} -> 200", False,
                      (rf.text[:100] if rf is not None else "error"))
    return ck("Fixture arrastre: tasas 2094/2096 + fuente con 4 compras "
              "(266-equivalentes) + ingresos misma/otra Linea + bloque "
              "sin-linea + flag ON", True,
              f"buyer_terms={state.buyer_terms} other_terms={state.other_terms} "
              f"tinta_terms={state.tinta_terms}")


def _expected_carryover():
    """Espejo INDEPENDIENTE de la spec §4 (no reusa el codigo del backend):
    fechas por timedelta del anchor y montos crudos, orden BR-CO-10
    extendido {line:0,cogs:1,purchase:2}."""
    rank = {"line": 0, "cogs": 1, "purchase": 2}
    rows = []
    imp = date(2096, 12, 15)
    for days, pct in state.buyer_terms:
        rows.append((imp + timedelta(days=int(days)), "purchase",
                     state.cc_buyer, 20_000_000.0 * float(pct)))
    anchor_no_terms = date(2097, 6, 1)
    rows.append((anchor_no_terms, "purchase", state.cc_null, 3_000_000.0))
    inc_other = date(2096, 12, 5)
    cost = 10_000_000.0 * 50.0 / 100.0
    for days, pct in state.other_terms:
        rows.append((inc_other + timedelta(days=int(days)), "cogs",
                     state.cc_other, cost * float(pct)))
    rows.append((date(2097, 2, 13), "line", state.cc_exp, 1_000_000.0))
    rows.sort(key=lambda t: (t[0], rank[t[1]]))
    return [(d.isoformat(), o, cc, a) for d, o, cc, a in rows]


def t11_ac_be8_5_carryover():
    payload = carry_payload(state.tgt_id)
    if payload is None or not payload.get("enabled"):
        return ck("AC-BE8-5 GET carryover 2097 habilitado", False, str(payload)[:120])
    ck("AC-BE8-5 source = la fuente 2096 elegida (BR-CO-02)",
       (payload.get("source") or {}).get("id_budget") == state.src_id,
       f"source={payload.get('source')}")
    expected = _expected_carryover()
    ok_list = close_tuples(payload_tuples(payload), expected)
    ck("AC-BE8-5 payload EXACTO (cuotas purchase de los terminos de la "
       "Linea, cogs del no-comprador, material line; cero filas extra) en "
       "orden fecha/origin/id", ok_list,
       f"got={payload_tuples(payload)} exp={expected}")
    origins = {(l["origin"], l["id_cost_center"]) for l in payload["lines"]}
    ck("AC-BE8-5 switch D-4/D-4': el CECO comprador NO tiene ninguna fila "
       "'cogs' (su pago se deriva de la compra) y si de 'purchase' — con "
       "compra e ingreso en el MISMO CECO ambas reglas coinciden",
       all(o != "cogs" for o, cc in origins if cc == state.cc_buyer)
       and ("purchase", state.cc_buyer) in origins)
    ck("AC-BE8-5/BR-CO-12: la compra anclada en N aparece SOLO como "
       "origin 'purchase' (jamas 'line') y sin terminos como cuota unica "
       "100 % en la fecha de importacion",
       ("purchase", state.cc_null) in origins
       and ("line", state.cc_null) not in origins
       and all(l["projected_amount"] != 3_000_000.0 or l["origin"] == "purchase"
               for l in payload["lines"]))
    pur_rows = [l for l in payload["lines"] if l["origin"] == "purchase"]
    ck("BR-PUR-05 forma de la fila purchase: line_type 'expense', "
       "id_budget_line null, budget_date=fecha de importacion, descripcion "
       "'Pago a proveedor (arrastre)'",
       all(l["line_type"] == "expense" and l["id_budget_line"] is None
           and l["description"] == "Pago a proveedor (arrastre)"
           and l["budget_date"] == "2096-12-15"
           for l in pur_rows if l["id_cost_center"] == state.cc_buyer))
    return True


def t11b_ac_be8b_payload():
    """AC-BE8b-1/2 cara PAYLOAD sobre el target 2097 (la lista EXACTA de
    t11 es el centinela global de cero dobles; aqui se etiquetan las
    caras individuales de la regla D-4' sobre el bloque 266-equivalente
    sembrado en t10)."""
    payload = carry_payload(state.tgt_id)
    if payload is None or not payload.get("enabled"):
        return ck("AC-BE8b GET carryover 2097 habilitado", False,
                  str(payload)[:120])
    cogs_ccs = {l["id_cost_center"] for l in payload["lines"]
                if l["origin"] == "cogs"}
    pur_ccs = {l["id_cost_center"] for l in payload["lines"]
               if l["origin"] == "purchase"}
    zonal = {state.cc266[c] for c in ("000101", "000201", "000202", "000302")}
    buyer_ccos = {state.cc266["000001"], state.cc266["000002"]}
    ck("AC-BE8b-1: compras en 000001/000002 switchan TODA la Linea — los "
       "ingresos ZONALES de esa misma Linea (000101/000201/000202/000302) "
       "PERDIERON su fila 'cogs' (cero doble cuenta 266)",
       cogs_ccs.isdisjoint(zonal | buyer_ccos | {state.cc_buyer}),
       f"cogs_ccs={sorted(cogs_ccs)} zonal={sorted(zonal)}")
    ck("AC-BE8b-1 (inverso): un CECO de OTRA Linea sin compras (control "
       f"linea {state.line_other}) CONSERVA su 'cogs' intacto",
       state.cc_other in cogs_ccs, f"cogs_ccs={sorted(cogs_ccs)}")
    ck("AC-BE8b-1/BR-CO-09 (fechas reales 30/01 y 30/05): las compras "
       "25M/18M cuyas cuotas caen todas dentro de N-1 NO aportan ninguna "
       "fila origin 'purchase' a N — solo ejercen su llave de Linea",
       pur_ccs.isdisjoint(buyer_ccos), f"pur_ccs={sorted(pur_ccs)}")
    ck("AC-BE8b-2 (payload): la compra sin Linea switcha SOLO su cc: — ni "
       "998801 (ingreso propio con compra) ni el centinela 998802 (sin "
       "compra) muestran 'cogs' (un ingreso sin Linea jamas arrastra: "
       "cuota unica en su ancla N-1), y la compra dirty de 998801 sigue "
       "presente como 'purchase' unica de su cc:",
       cogs_ccs.isdisjoint({state.cc_null, state.cc_null2})
       and ("purchase", state.cc_null) in
       {(l["origin"], l["id_cost_center"]) for l in payload["lines"]},
       f"cogs_ccs={sorted(cogs_ccs)} pur={sorted(pur_ccs)}")
    return True


def _unit_planning():
    """Importa el MISMO codigo del backend (modulo montado en el contenedor
    dev :8003) dentro de este proceso para checks unitarios de la Enmienda
    A-02, con sesion SQLAlchemy propia contra la BD dev de .env_test. Los
    env vars de app/settings.py se sintetizan ANTES del import (sin .env en
    el host); `import app.api` va primero porque es el orden que rompe el
    ciclo core.auth <-> app.api.utils en el arranque real (importar
    app.crud directamente lo dispararia)."""
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


def t11c_unit_a02():
    """AC-BE8b-2/3 + NFR-BE8-2 MEDIDO, in-process sobre la misma BD dev con
    el fixture vivo de t10:

    * el par de claves D-4' de get_purchasing_source_keys es EXACTO (las
      Lineas de todas las compras + solo el CECO sin Linea comprador en
      cc:; el centinela sin compra 998802 jamas entra) — esta es la senal
      discriminante del switch cc:, que a nivel payload es invisible por
      construccion (un ingreso sin Linea nunca deriva cuota en N: D-S7-4
      ancla en N-1);
    * la derivacion SIN claves (comportamiento pre-A-02) si produce las
      cuotas cogs de los zonales Kyly/Tinta en 2097 (la doble cuenta del
      reporte) y CON las claves D-4' desaparecen todas, mientras la Linea
      control conserva las suyas;
    * el conteo real de SELECTs por carryover completo: 6 con compras /
      5 sin ellas (BE-S7 = 4 ⇒ +2/+1, NFR-BE8-2 intacto), constante
      frente a los 12 filas sembradas en t10."""
    try:
        planning, SessionLocal, engine = _unit_planning()
    except Exception as e:
        return ck("Unit A-02: import app.crud.budget.planning in-process",
                  False, f"{type(e).__name__}: {str(e)[:130]}")
    ck("Unit A-02: import app.crud.budget.planning in-process (mismo "
       "modulo que sirve :8003 via volumen montado)", True)
    db = SessionLocal()
    try:
        lines, ccs = planning.get_purchasing_source_keys(db, state.src_id)
        exp_lines = {state.lines266["000001"], state.lines266["000002"],
                     state.line_buyer}
        ck("AC-BE8b-2 unit: claves de la fuente 2096 == (lines "
           "{Kyly,Tinta,buyer}, cc {998801}) — una compra sin Linea NUNCA "
           "contamina el set de lines y 998802 (sin compra) no aparece",
           lines == exp_lines and ccs == {state.cc_null},
           f"lines={sorted(lines)} ccs={sorted(ccs)}")
        empty = planning.get_purchasing_source_keys(db, state.nosrc_id)
        ck("AC-BE8b-3 unit (centinela): fuente SIN compras => K=(∅,∅) => "
           "scan FE-S7/A-01 intacto (exclusion inerte)",
           empty == (set(), set()), f"k={empty}")
        zonal = {state.cc266[c] for c in ("000101", "000201", "000202",
                                          "000302")}
        legacy = planning.get_carryover_cogs_lines(
            db, state.src_id, SRC_YEAR, TGT_YEAR)
        legacy_ccs = {r["id_cost_center"] for r in legacy}
        switched = planning.get_carryover_cogs_lines(
            db, state.src_id, SRC_YEAR, TGT_YEAR,
            purchasing_source_keys=(lines, ccs))
        switched_ccs = {r["id_cost_center"] for r in switched}
        ck(f"AC-BE8b-1 unit (doble cuenta del reporte): SIN claves los 4 "
           f"CECOS zonales ({sorted(zonal)}) SI derivan cuotas cogs 2097 "
           f"({len(legacy)} filas), y el comprador de su propia Linea "
           "tambien",
           zonal <= legacy_ccs and state.cc_buyer in legacy_ccs,
           f"legacy={len(legacy)} ccs={sorted(legacy_ccs)}")
        ck("AC-BE8b-1 unit (switch D-4'): CON las claves de la fuente "
           "cero filas cogs en las Lineas compradoras — el payload "
           "resultante es SOLO el cogs del control (misma señal que la "
           "lista exacta HTTP de t11)",
           switched_ccs == {state.cc_other} and len(switched) < len(legacy),
           f"switched={len(switched)} ccs={sorted(switched_ccs)}")
        only_tinta = planning.get_carryover_cogs_lines(
            db, state.src_id, SRC_YEAR, TGT_YEAR, purchasing_source_keys=(
                {state.lines266["000002"]}, set()))
        only_tinta_ccs = {r["id_cost_center"] for r in only_tinta}
        ck("AC-BE8b-2 unit (predicado, rama line:): pasar SOLO la llave "
           "Tinta switcha los zonales de Tinta y deja intactos Kyly "
           "(comprador aparte), el del buyer y el control",
           only_tinta_ccs == {state.cc_buyer, state.cc266["000101"],
                              state.cc266["000201"], state.cc_other},
           f"ccs={sorted(only_tinta_ccs)}")
        # NFR-BE8-2 medido con eventos del engine (solo SELECTs):
        from sqlalchemy import event
        counter = {"n": 0}

        def _count(conn, cursor, statement, parameters, context,
                   executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            counter["n"] = 0
            built_src = planning.build_carryover_payload_lines(
                db, state.src_id, SRC_YEAR, TGT_YEAR)
            n_src = counter["n"]
            counter["n"] = 0
            planning.build_carryover_payload_lines(
                db, state.nosrc_id, NOSRC_YEAR, NOTGT_YEAR)
            n_nosrc = counter["n"]
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        ck("NFR-BE8-2 (medido por eventos SQLAlchemy, misma fuente con "
           "12 filas): carryover completo = 6 SELECT con compras / 5 sin "
           "compras (BE-S7 pagaba 4 ⇒ +2/+1 constantes)",
           n_src == 6 and n_nosrc == 5, f"con={n_src} sin={n_nosrc}")
        http_payload = carry_payload(state.tgt_id) or {}
        ck("Paridad unit-vs-HTTP: build_carryover_payload_lines in-process "
           "coincide con la respuesta de la API (mismo codigo, cero "
           "deriva)",
           [(l["id_cost_center"], l["origin"], l["projected_amount"])
            for l in http_payload.get("lines", [])]
           == [(l.id_cost_center, l.origin, l.projected_amount)
               for l in built_src],
           f"http={len(http_payload.get('lines', []))} unit={len(built_src)}")
    finally:
        db.close()
    return True


def t12_nfr_be8_3_no_purchase():
    """NFR-BE8-3 / AC-BE8b-3: fuente SIN compras => payload sin origin
    'purchase' y material+cogs EXACTOS — con A-02 las claves quedan
    (∅,∅) (check unitario en t11c) y el contrato es byte-identico al de
    A-01."""
    payload = carry_payload(state.notgt_id)
    if payload is None:
        return ck("NFR-BE8-3 carryover 2095 legible", False)
    got = payload_tuples(payload)
    cost = 10_000_000.0 * 50.0 / 100.0
    expected = []
    for days, pct in state.other_terms:
        expected.append(((date(2094, 12, 5) + timedelta(days=int(days)))
                         .isoformat(), "cogs", state.cc_other, cost * float(pct)))
    expected.append(("2095-01-10", "line", state.cc_exp, 500_000.0))
    expected.sort(key=lambda t: (t[0], {"line": 0, "cogs": 1}[t[1]]))
    ok = close_tuples(got, expected) and all(
        l["origin"] != "purchase" for l in payload["lines"])
    return ck("NFR-BE8-3/AC-BE8b-3 escenario sin compras: payload == "
              "line+cogs de siempre (identico a A-01), cero 'purchase'",
              ok, f"got={got} exp={expected}")


def t13_cleanup_bench_and_report():
    """Elimina el banco del 69 y sus clones (delete-draft) y los uploads
    de AC-BE8-4; verifica que el 69 NO fue tocado."""
    ok_del = True
    for bid in filter(None, (state.clone2_id, state.clone_id)):
        r = api("DELETE", f"/budget/{bid}")
        ok_del &= r is not None and r.status_code == 200
    for bid in state.upload_ids:
        r = api("DELETE", f"/budget/{bid}")
        ok_del &= r is not None and r.status_code == 200
    ck("delete-draft: banco 69 + clon x1.2 + uploads 'PURC *' eliminados "
       "via DELETE /budget/{id}", ok_del)
    left = int(sql_scalar("SELECT count(*) FROM budgets WHERE budget_name "
                          f"LIKE '{MARK}%' AND budget_year NOT IN "
                          f"({','.join(map(str, SENTINELS))})"))
    r69 = planning_row(69, BENCH_69_YEAR)
    raw69 = run_sql("SELECT count(*) FROM budget_lines WHERE id_budget=69 "
                    "AND line_type='PURCHASE'", fetch=True)
    ck("AC-BE8-3 el presupuesto 69 (fuente del banco) NO fue mutado",
       left == 0 and r69 is not None and int(raw69[0][0]) == 0
       and r69["status"] == "active",
       f"restos={left} pur69={raw69[0][0] if raw69 else '?'}")
    return True


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("Budget PURCHASE Lines Smoke (BE-S8-BUDGET-PURCHASES)")
    print("=" * 64)
    print(f"Base URL : {BASE_URL}")
    print(f"Banco: clon draft del presupuesto 69 | centinelas: "
          f"{SRC_YEAR}->{TGT_YEAR} (+bloque A-02/266), "
          f"{NOSRC_YEAR}->{NOTGT_YEAR}, upload {UP_YEAR}")
    print()

    print("-- login + pre-clean (idempotencia) --")
    if not t01_login():
        print("ABORT: sin JWT no se puede ejecutar el smoke test")
        return 1
    preclean()
    if not t02_clone_bench():
        print("ABORT: banco de pruebas no pudo crearse")
        postclean()
        return 1
    print()

    tests = [
        t03_ac_be8_1_create,
        t04_ac_be8_1_guards,
        t05_ac_be8_2_update_guards,
        t06_ac_be8_3_listing_totals,
        t07_ac_be8_6_clone_scaling,
        t08_ac_be8_4_upload3,
        t09_ac_be8_4_rejections,
        t09b_ac_be8a1_real_fixture,
        t10_seed_carryover,
        t11_ac_be8_5_carryover,
        t11b_ac_be8b_payload,
        t11c_unit_a02,
        t12_nfr_be8_3_no_purchase,
        t13_cleanup_bench_and_report,
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
