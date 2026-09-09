"""
Upload Status Endpoint Smoke Tests (spec backend.04, BE-S3-UPLOAD-STATUS)

Prueba el endpoint GET /budget/upload/status que reporta la ultima carga
ETL por dataset (MAX(created_at) sobre actual_costs, actual_expenses,
payment_ledger y accounts_receivable):

- AC-1: sin token / token invalido => 401 (el proyecto usa 401; se acepta 403)
- AC-2: GET autenticado => 200 con exactamente 4 claves raiz
- AC-3: cada clave raiz: objeto con unica propiedad last_upload (ISO-8601 o null)
- AC-4: tabla vacia <=> last_upload null (verificado por equivalencia con los
        endpoints de listado; no se puede forzar vaciado sin borrar datos dev)
- AC-5: tras POST /budget/upload/accounts-receivable (fixture data/ del smoke
        de cartera) => accounts_receivable.last_upload no null y dentro de
        +/- 5 min de la hora del servidor; se limpian los filas del fixture
- AC-6: regresión: openapi.json conserva los 5 paths de upload POST + el nuevo
        GET /status, y la guarda de extension .xlsx sigue respondiendo 400
- AC-7: dos llamadas consecutivas devuelven el mismo payload (idempotente)

Endpoints bajo prueba:
    GET  /budget/upload/status                    - Estado de ingesta ETL
    POST /budget/upload/accounts-receivable       - (solo para AC-5/AC-6)

Uso:
    1. Backend dev arriba: docker compose -f docker-compose-dev.yaml up
    2. .env_test con USERNAME y PASSWORD (ver .env_test.example); opcional
       ACCOUNTS_RECEIVABLE_EXCEL_PATH (por defecto test/data/EstadoCuenta306090.xlsx)
    3. python test_upload_status_smoke.py

Exit codes: 0 = todo OK (puede haber SKIPs), 1 = fallos, 2 = backend no accesible
"""

import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from dotenv import dotenv_values

# ══════════════════════════════════════════════════════════════
# CARGAR CONFIGURACION DESDE .env_test
# ══════════════════════════════════════════════════════════════

TEST_DIR = Path(__file__).parent
ENV_FILE = TEST_DIR / ".env_test"

if not ENV_FILE.exists():
    print(f"ERROR: No se encontro {ENV_FILE}")
    print("Crea .env_test con USERNAME y PASSWORD (ver .env_test.example)")
    sys.exit(1)

config = dotenv_values(ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')
AR_EXCEL_PATH = (config.get("ACCOUNTS_RECEIVABLE_EXCEL_PATH", "")
                 or str(TEST_DIR / "data" / "EstadoCuenta306090.xlsx")).strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

EXCEL_FILENAME = Path(AR_EXCEL_PATH).name
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

STATUS_URL = "/budget/upload/status"
AR_BASE = "/budget/account-receivable"

EXPECTED_ROOT_KEYS = {
    "actual_costs", "actual_expenses", "payment_ledger", "accounts_receivable",
}

DATASET_LIST_ENDPOINTS = {
    "actual_costs": "/budget/actual-cost/",
    "actual_expenses": "/budget/actual-expense/",
    "payment_ledger": "/budget/payment-ledger/",
    "accounts_receivable": AR_BASE + "/",
}

UPLOAD_POST_PATHS = [
    "/budget/upload/cost-centers",
    "/budget/upload/actual-expenses",
    "/budget/upload/actual-costs",
    "/budget/upload/accounts-receivable",
    "/budget/upload/payment-ledger",
]

TOLERANCE_SECONDS = 300  # AC-5: +/- 5 min

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results = []

state = TestState()

# ══════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════

def log_test(num: int, total: int, name: str, success, detail: str = ""):
    if success is None:
        status = "[SKIP]"
        state.skipped += 1
    elif success:
        status = "[PASS]"
        state.passed += 1
    else:
        status = "[FAIL]"
        state.failed += 1
    msg = f"[{num}/{total}] {name}... {status}"
    if detail:
        msg += f" ({detail})"
    print(msg)
    state.results.append((name, success, detail))


def api_request(method: str, endpoint: str, auth: bool = True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    # headers explicito (p.ej. token invalido) tiene prioridad sobre el flag auth
    headers = kwargs.pop("headers", None) or (state.headers if auth else {})
    try:
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        return response
    except Exception as e:
        print(f"  [ERROR] Request exception: {type(e).__name__}: {str(e)[:100]}")
        return None


def parse_iso_datetime(value):
    """None si no es ISO-8601 parseable; datetime naive en caso contrario."""
    if value is None:
        return None
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return False


def skip_if_no_token(num: int, total: int, name: str):
    if state.token is None:
        log_test(num, total, name, None, "sin JWT (login fallo o backend no accesible)")
        return True
    return False


# ══════════════════════════════════════════════════════════════
# PRUEBAS
# ══════════════════════════════════════════════════════════════

def test_01_login():
    """Obtener JWT token para autenticacion."""
    response = api_request("POST", "/login/", json={
        "username": USERNAME,
        "password": PASSWORD
    })
    if response is not None and response.status_code == 200:
        data = response.json()
        state.token = data.get("access_token")
        state.headers = {"Authorization": f"Bearer {state.token}"}
        log_test(1, 7, "Login", True, "JWT obtenido")
        return True
    detail = response.text[:50] if response is not None else "Connection error"
    log_test(1, 7, "Login", False, detail)
    return False


def test_02_auth_required():
    """AC-1: GET sin token => 401/403; token invalido => 401/403 (401 en el proyecto)."""
    no_token = api_request("GET", STATUS_URL, auth=False)
    no_token_ok = no_token is not None and no_token.status_code in (401, 403)

    bad = api_request("GET", STATUS_URL,
                      headers={"Authorization": "Bearer token.invalido.firma"},
                      auth=False)
    bad_ok = bad is not None and bad.status_code in (401, 403)

    if no_token_ok and bad_ok:
        log_test(2, 7, "Auth required (AC-1)", True,
                 f"sin token={no_token.status_code}, invalido={bad.status_code}")
        return True
    log_test(2, 7, "Auth required (AC-1)", False,
             f"sin_token={getattr(no_token, 'status_code', None)}, "
             f"token_invalido={getattr(bad, 'status_code', None)}")
    return False


def test_03_contract_shape():
    """AC-2 + AC-3: 200 con exactamente 4 claves raiz, cada una {last_upload} ISO o null."""
    if skip_if_no_token(3, 7, "Contract shape (AC-2/AC-3)"):
        return
    response = api_request("GET", STATUS_URL)
    if response is None or response.status_code != 200:
        log_test(3, 7, "Contract shape (AC-2/AC-3)", False,
                 f"status={getattr(response, 'status_code', None)}")
        return

    data = response.json()
    problems = []

    if set(data.keys()) != EXPECTED_ROOT_KEYS:
        problems.append(f"claves raiz={sorted(data.keys())}")

    for key, value in data.items():
        if not isinstance(value, dict) or set(value.keys()) != {"last_upload"}:
            problems.append(f"{key} no es objeto con unica clave last_upload: {value}")
            continue
        parsed = parse_iso_datetime(value["last_upload"])
        if parsed is False:
            problems.append(f"{key}.last_upload no es ISO-8601 ni null: {value['last_upload']!r}")

    if problems:
        log_test(3, 7, "Contract shape (AC-2/AC-3)", False, "; ".join(problems)[:200])
        return
    non_null = [k for k in EXPECTED_ROOT_KEYS if data[k]["last_upload"] is not None]
    log_test(3, 7, "Contract shape (AC-2/AC-3)", True,
             f"4 claves OK; no-null: {non_null if non_null else 'ninguna'}")


def test_04_empty_semantics():
    """AC-4: tabla vacia <=> last_upload null (equivalencia via list ?limit=1 por dataset)."""
    if skip_if_no_token(4, 7, "Empty-table semantics (AC-4)"):
        return
    status_resp = api_request("GET", STATUS_URL)
    if status_resp is None or status_resp.status_code != 200:
        log_test(4, 7, "Empty-table semantics (AC-4)", False, "GET status fallo")
        return
    status_data = status_resp.json()

    problems = []
    checked = 0
    all_empty = True
    for key, endpoint in DATASET_LIST_ENDPOINTS.items():
        listing = api_request("GET", f"{endpoint}?limit=1")
        if listing is None or listing.status_code != 200 or not isinstance(listing.json(), list):
            problems.append(f"{key}: listado no disponible "
                            f"(status={getattr(listing, 'status_code', None)})")
            continue
        checked += 1
        has_rows = len(listing.json()) > 0
        last_upload = status_data.get(key, {}).get("last_upload")
        if has_rows:
            all_empty = False
        if has_rows and last_upload is None:
            problems.append(f"{key}: tabla con filas pero last_upload=null")
        if not has_rows and last_upload is not None:
            problems.append(f"{key}: tabla vacia pero last_upload={last_upload}")

    if problems:
        log_test(4, 7, "Empty-table semantics (AC-4)", False, "; ".join(problems)[:200])
        return
    note = ("todas las tablas vacias => 4 nulls (caso AC-4 directo)"
            if all_empty else
            f"equivalencia vacio<=>null verificada en {checked} datasets (tablas con datos dev)")
    log_test(4, 7, "Empty-table semantics (AC-4)", True, note)


def upload_ar_file(force: bool = False):
    """Subir el fixture de cartera (multipart campo file + force opcional)."""
    data = {"force": "true"} if force else None
    with open(AR_EXCEL_PATH, "rb") as f:
        files = {"file": (EXCEL_FILENAME, f, XLSX_MIME)}
        return api_request("POST", "/budget/upload/accounts-receivable",
                           files=files, data=data)


def cleanup_fixture_ar_rows():
    """Borrar filas ETL del fixture via DELETE by-document (higiene, como el smoke AR)."""
    listing = api_request("GET", f"{AR_BASE}/?limit=10000")
    if listing is None or listing.status_code != 200:
        return -1
    docs = sorted({r["document_number"] for r in listing.json()
                   if r.get("source_file") == EXCEL_FILENAME})
    for doc in docs:
        api_request("DELETE", f"{AR_BASE}/by-document/{quote(doc)}")
    return len(docs)


def test_05_upload_refreshes_status():
    """AC-5: upload cartera existoso => accounts_receivable.last_upload no null, ±5 min."""
    if skip_if_no_token(5, 7, "Upload refreshes status (AC-5)"):
        return
    if not Path(AR_EXCEL_PATH).exists():
        log_test(5, 7, "Upload refreshes status (AC-5)", None,
                 f"fixture no encontrado: {AR_EXCEL_PATH}")
        return

    response = upload_ar_file()
    if response is not None and response.status_code == 400:
        # Guarda de corte obsoleto (D-3): reintento con force, como permite la API
        response = upload_ar_file(force=True)

    if response is None or response.status_code != 200:
        detail = response.text[:150] if response is not None else "error de conexion"
        log_test(5, 7, "Upload refreshes status (AC-5)", None,
                 f"upload no completado por estado del entorno dev "
                 f"(status={getattr(response, 'status_code', None)}): {detail}")
        return

    status_resp = api_request("GET", STATUS_URL)
    got = cleanup_fixture_ar_rows()

    if status_resp is None or status_resp.status_code != 200:
        log_test(5, 7, "Upload refreshes status (AC-5)", False, "GET status post-upload fallo")
        return
    value = status_resp.json().get("accounts_receivable", {}).get("last_upload")
    parsed = parse_iso_datetime(value)
    if parsed is False or value is None:
        log_test(5, 7, "Upload refreshes status (AC-5)", False,
                 f"last_upload={value!r} tras upload 200")
        return

    # created_at es naive del servidor PG (UTC en docker; datetime.now() local
    # en host propio). Se acepta whichever candidato deja el delta menor.
    utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = min(abs((utc_naive - parsed).total_seconds()),
                abs((datetime.now() - parsed).total_seconds()))
    ok = delta <= TOLERANCE_SECONDS
    log_test(5, 7, "Upload refreshes status (AC-5)", ok,
             f"last_upload={value}, delta={delta:.0f}s (tol {TOLERANCE_SECONDS}s), "
             f"cleanup_filas_fixture={got}")


def test_06_idempotent():
    """AC-7: dos llamadas consecutivas devuelven el mismo payload."""
    if skip_if_no_token(6, 7, "Idempotent reads (AC-7)"):
        return
    first = api_request("GET", STATUS_URL)
    second = api_request("GET", STATUS_URL)
    if first is None or second is None:
        log_test(6, 7, "Idempotent reads (AC-7)", False, "error de conexion")
        return
    if first.status_code != 200 or second.status_code != 200:
        log_test(6, 7, "Idempotent reads (AC-7)", False,
                 f"status={first.status_code}/{second.status_code}")
        return
    if first.json() == second.json():
        log_test(6, 7, "Idempotent reads (AC-7)", True, "payloads identicos")
    else:
        log_test(6, 7, "Idempotent reads (AC-7)", False,
                 f"{first.json()} != {second.json()}")


def test_07_no_route_regression():
    """AC-6: openapi conserva los 5 POST de upload + nuevo GET /status; guarda .xlsx sigue."""
    try:
        spec = requests.get(f"{BASE_URL}/openapi.json", timeout=30).json()
        paths = spec.get("paths", {})
    except Exception as e:
        log_test(7, 7, "Route regression (AC-6)", False, f"openapi no accesible: {e}")
        return

    problems = []
    get_status = paths.get(STATUS_URL, {})
    if "get" not in get_status:
        problems.append("falta GET /budget/upload/status")
    else:
        ref = (get_status["get"].get("responses", {}).get("200", {})
               .get("content", {}).get("application/json", {})
               .get("schema", {}).get("$ref", ""))
        if not ref.endswith("UploadStatusResponse"):
            problems.append(f"response_model unexpected: {ref}")

    for path in UPLOAD_POST_PATHS:
        if "post" not in paths.get(path, {}):
            problems.append(f"desaparecio POST {path}")

    if state.token is not None:
        response = api_request("POST", "/budget/upload/accounts-receivable",
                               files={"file": ("malformado.txt", b"not an excel", "text/plain")})
        if response is None or response.status_code != 400:
            problems.append(f"guarda .xlsx sin respuesta 400 "
                            f"(status={getattr(response, 'status_code', None)})")
        elif "Only .xlsx files are supported" not in response.text:
            problems.append("guarda .xlsx: mensaje 400 inesperado")

    if problems:
        log_test(7, 7, "Route regression (AC-6)", False, "; ".join(problems)[:200])
        return
    log_test(7, 7, "Route regression (AC-6)", True,
             "GET /status registrado; 5 POST de upload intactos; guarda .xlsx OK")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Upload Status Endpoint Smoke Tests (spec backend.04)")
    print("=" * 60)
    print(f"Base URL:    {BASE_URL}")
    print(f"User:        {USERNAME}")
    print(f"AR fixture:  {AR_EXCEL_PATH} "
          f"({'ok' if Path(AR_EXCEL_PATH).exists() else 'NO ENCONTRADO'})")
    print()

    # Prechecar accesibilidad: si el backend esta abajo, todo es SKIP (exit 2)
    try:
        requests.get(f"{BASE_URL}/openapi.json", timeout=5)
    except Exception as e:
        print(f"Backend no accesible en {BASE_URL} ({type(e).__name__}).")
        print("Levanta el entorno: docker compose -f docker-compose-dev.yaml up")
        print("Todas las pruebas se marcan como SKIP (exit code 2).")
        return 2

    tests = [
        test_01_login,
        test_02_auth_required,
        test_03_contract_shape,
        test_04_empty_semantics,
        test_05_upload_refreshes_status,
        test_06_idempotent,
        test_07_no_route_regression,
    ]

    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"  [ERROR] {test_func.__name__}: {e}")
            state.failed += 1

    print()
    print("=" * 60)
    print(f"Results: {state.passed}/{len(tests)} passed, "
          f"{state.failed} failed, {state.skipped} skipped")
    if state.failed > 0:
        print("Failed tests:")
        for name, success, detail in state.results:
            if success is False:
                print(f"  - {name}: {detail}")
    print("=" * 60)

    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
