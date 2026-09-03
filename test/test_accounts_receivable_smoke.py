"""
Accounts Receivable Module Smoke Tests (spec backend.02_08)

Prueba los endpoints del modulo de cuentas por cobrar:
- CRUD individual (create, read, list, update, delete)
- Campos nuevos de trazabilidad (customer_document, identification_original,
  statement_date) y default status="OPEN" (sin ge=0 en montos, A-2)
- ETL upload desde Excel (EstadoCuenta306090.xlsx)
- Reemplazo atomico idempotente por documento (AC-4)
- DELETE por document_number (by-document) con 404 en ausencia
- Validaciones: extension .xlsx, auth JWT

Endpoints bajo prueba:
    GET    /budget/account-receivable/                        - Listar con filtros
    GET    /budget/account-receivable/{id}                    - Obtener por ID
    POST   /budget/account-receivable/                        - Crear
    PUT    /budget/account-receivable/{id}                    - Actualizar
    DELETE /budget/account-receivable/{id}                    - Eliminar por ID
    DELETE /budget/account-receivable/by-document/{doc}       - Eliminar por documento
    POST   /budget/upload/accounts-receivable                 - ETL upload (force opcional)

Verificacion MANUAL (no cubierta aqui, requiere modificar el Excel o la BD):
    AC-6 contact fallback · AC-7 cierre D-2 · AC-8 guarda de corte/force D-3 ·
    AC-9 rollback por cliente no resuelto · nullify FK payment_ledger (AC-11)

Uso:
    1. Ejecutar crm_backend/sql/migrations/02_08_accounts_receivable_add_columns.sql
       en la BD dev (ALTER TABLE ... ADD COLUMN IF NOT EXISTS) ANTES de correr
    2. Asegurar backend dev arriba: docker compose -f docker-compose-dev.yaml up
    3. (Opcional) ACCOUNTS_RECEIVABLE_EXCEL_PATH en .env_test; por defecto usa
       test/data/EstadoCuenta306090.xlsx
    4. python test_accounts_receivable_smoke.py
"""

import sys
import time
import requests
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

if not Path(AR_EXCEL_PATH).exists():
    print(f"ERROR: No se encontro {AR_EXCEL_PATH}")
    sys.exit(1)

EXCEL_FILENAME = Path(AR_EXCEL_PATH).name
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Premisas verificadas contra EstadoCuenta306090.xlsx (spec §4.1 / AC-2 / AC-3)
EXPECTED_RAW = 276          # filas crudas
EXPECTED_SUBTOTALS = 155    # filas sin Doc (subtotales excluidos)
EXPECTED_INSERTED = 121     # filas de detalle insertadas
EXPECTED_DOCS_UNIQUE = 119  # documentos distintos
EXPECTED_SUM = 439696679.72 # SUM(Valor Total) del detalle
EXPECTED_CUTOFF = "2026-08-26"
EXPECTED_NEGATIVES = 56     # filas con total_amount < 0 (A-2)
EXPECTED_RC_DOCS = 51       # filas rc* => legacy debt (A-4/A-5)
DUPLICATE_DOC = "FVFE1595"  # documento duplicado dentro del archivo (A-3)
ALLOWED_BUCKETS = {None, "current", "1_to_30", "31_to_60", "61_to_90", "over_90"}

AR_BASE = "/budget/account-receivable"

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.created_ar_ids = []
        self.pre_upload_count = 0
        self.etl_balance_sum = 0.0
        self.etl_docs = set()
        self.upload_time = 0.0
        self.passed = 0
        self.failed = 0
        self.results = []

state = TestState()

# ══════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════

def log_test(num: int, total: int, name: str, success: bool, detail: str = ""):
    status = "[PASS]" if success else "[FAIL]"
    msg = f"[{num}/{total}] {name}... {status}"
    if detail:
        msg += f" ({detail})"
    print(msg)
    if success:
        state.passed += 1
    else:
        state.failed += 1
    state.results.append((name, success, detail))


def api_request(method: str, endpoint: str, auth: bool = True, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = state.headers if auth else {}
    try:
        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        return response
    except Exception as e:
        print(f"  [ERROR] Request exception: {type(e).__name__}: {str(e)[:100]}")
        return None


def get_all_ar_rows():
    """Traer todos los registros (limite alto) para conteos client-side."""
    response = api_request("GET", f"{AR_BASE}/?limit=10000")
    if response is not None and response.status_code == 200:
        return response.json()
    return None


def filter_etl_rows(all_rows):
    """Registros cuyo source_file == nombre del archivo subido."""
    return [r for r in all_rows if r.get("source_file") == EXCEL_FILENAME]


def upload_ar_file(force: bool = False, path: str = None, filename: str = None,
                   content_type: str = XLSX_MIME, fileobj: bytes = None):
    """Subir multipart (campo file + flag force opcional) y medir tiempo."""
    data = {"force": "true"} if force else None
    path = path or AR_EXCEL_PATH
    filename = filename or Path(path).name

    def send(fobj):
        files = {"file": (filename, fobj, content_type)}
        t0 = time.time()
        response = api_request("POST", "/budget/upload/accounts-receivable",
                               files=files, data=data)
        elapsed = time.time() - t0
        return response, elapsed

    if fileobj is not None:
        return send(fileobj)
    with open(path, "rb") as f:
        return send(f)


def check_close(actual, expected, tol=0.005):
    try:
        return abs(float(actual) - float(expected)) <= tol
    except (TypeError, ValueError):
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
        log_test(1, 16, "Login", True, "JWT obtenido")
        return True
    else:
        detail = response.text if response is not None else "Connection error"
        log_test(1, 16, "Login", False, detail[:50])
        return False


def test_02_create_account_receivable():
    """Crear registro minimo valido (sin FKs, con campos de trazabilidad D-1/D-3)."""
    ar_data = {
        "document_number": "TESTAR001",
        "due_date": "2026-01-15",
        "total_amount": 1500.00,
        "balance": 1500.00,
        "source_file": "test_smoke",
        "customer_document": 111222333,
        "identification_original": "CC 111222333 -",
        "statement_date": "2026-01-01",
    }

    response = api_request("POST", f"{AR_BASE}/", json=ar_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        ar_id = data.get("id_account_receivable")
        state.created_ar_ids.append(ar_id)
        traz_ok = (data.get("customer_document") == 111222333
                   and data.get("identification_original") == "CC 111222333 -"
                   and data.get("statement_date") == "2026-01-01")
        if traz_ok:
            log_test(2, 16, "Create account receivable", True,
                     f"id={ar_id}, trazabilidad D-1/D-3 persistida")
            return True
        else:
            log_test(2, 16, "Create account receivable", False,
                     f"creado id={ar_id} pero campos nuevos no coinciden: "
                     f"{data.get('customer_document')}/"
                     f"{data.get('identification_original')}/"
                     f"{data.get('statement_date')}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(2, 16, "Create account receivable", False, detail[:120])
        return False


def test_03_get_account_receivable():
    """GET /{id}: coincide id/document y las 3 claves nuevas estan presentes."""
    if not state.created_ar_ids:
        log_test(3, 16, "Get account receivable", False, "no record created")
        return False

    ar_id = state.created_ar_ids[-1]
    response = api_request("GET", f"{AR_BASE}/{ar_id}")
    if response is not None and response.status_code == 200:
        data = response.json()
        has_new_keys = all(k in data for k in
                           ("customer_document", "identification_original",
                            "statement_date"))
        if (data.get("id_account_receivable") == ar_id
                and data.get("document_number") == "TESTAR001"
                and has_new_keys):
            log_test(3, 16, "Get account receivable", True,
                     f"id={ar_id}, claves nuevas presentes")
            return True
        else:
            log_test(3, 16, "Get account receivable", False,
                     f"mismatch o claves nuevas ausentes (keys={has_new_keys})")
            return False
    else:
        log_test(3, 16, "Get account receivable", False,
                 f"status {response.status_code if response is not None else 'error'}")
        return False


def test_04_list_and_status_filter():
    """Listar con limit alto; default status OPEN (test 2) visible en ?status=OPEN."""
    response = api_request("GET", f"{AR_BASE}/?limit=10000")
    if response is None or response.status_code != 200:
        log_test(4, 16, "List account receivable", False, "list failed")
        return False
    all_rows = response.json()

    response = api_request("GET", f"{AR_BASE}/?status=OPEN&limit=10000")
    if response is None or response.status_code != 200:
        log_test(4, 16, "List account receivable", False, "status filter failed")
        return False
    open_rows = response.json()

    testar = [r for r in all_rows if r.get("document_number") == "TESTAR001"]
    in_open = any(r.get("document_number") == "TESTAR001" for r in open_rows)
    if (testar and testar[0].get("status") == "OPEN"
            and in_open
            and all(r.get("status") == "OPEN" for r in open_rows)):
        log_test(4, 16, "List account receivable", True,
                 f"total={len(all_rows)}, OPEN={len(open_rows)}, "
                 "default OPEN sin enviar status")
        return True
    else:
        log_test(4, 16, "List account receivable", False,
                 f"testar={[t.get('status') for t in testar]}, "
                 f"in_open={in_open}")
        return False


def test_05_update_account_receivable():
    """PUT /{id}: actualizar montos y status a PARTIAL."""
    if not state.created_ar_ids:
        log_test(5, 16, "Update account receivable", False, "no record to update")
        return False

    ar_id = state.created_ar_ids[-1]
    update_data = {
        "document_number": "TESTAR001",
        "due_date": "2026-01-15",
        "total_amount": 2750.50,
        "paid_amount": 1000.50,
        "balance": 1750.00,
        "status": "PARTIAL",
        "source_file": "test_smoke",
    }

    response = api_request("PUT", f"{AR_BASE}/{ar_id}", json=update_data)
    if response is not None and response.status_code == 200:
        data = response.json()
        if (check_close(data.get("total_amount"), 2750.50)
                and check_close(data.get("balance"), 1750.00)
                and data.get("status") == "PARTIAL"):
            log_test(5, 16, "Update account receivable", True,
                     "amounts/status=PARTIAL updated")
            return True
        else:
            log_test(5, 16, "Update account receivable", False,
                     "update not applied correctly")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(5, 16, "Update account receivable", False, detail[:120])
        return False


def test_06_negative_amount_allowed():
    """A-2/§4.4: monto negativo aceptado (sin ge=0) y default OPEN."""
    ar_data = {
        "document_number": "TESTAR002",
        "due_date": "2026-02-10",
        "total_amount": -500.00,
        "balance": -500.00,
        "source_file": "test_smoke",
    }

    response = api_request("POST", f"{AR_BASE}/", json=ar_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        ar_id = data.get("id_account_receivable")
        state.created_ar_ids.append(ar_id)
        if check_close(data.get("total_amount"), -500.00) and data.get("status") == "OPEN":
            log_test(6, 16, "Negative amount allowed", True,
                     f"negativo aceptado, default OPEN, id={ar_id}")
            return True
        else:
            log_test(6, 16, "Negative amount allowed", False,
                     f"status_resp={data.get('status')}, "
                     f"amount={data.get('total_amount')}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(6, 16, "Negative amount allowed", False,
                 f"rejected: {detail[:120]}")
        return False


def test_07_auth_required():
    """AC-14: upload y DELETE by-document sin token => 401/403."""
    upload_resp = api_request("POST", "/budget/upload/accounts-receivable", auth=False,
                              files={"file": ("x.xlsx", b"dummy", XLSX_MIME)})
    upload_rejected = upload_resp is not None and upload_resp.status_code in (401, 403)

    delete_resp = api_request("DELETE", f"{AR_BASE}/by-document/TESTAR002", auth=False)
    delete_rejected = delete_resp is not None and delete_resp.status_code in (401, 403)

    if upload_rejected and delete_rejected:
        log_test(7, 16, "Auth required", True,
                 f"upload={upload_resp.status_code}, delete={delete_resp.status_code}")
        return True
    else:
        log_test(7, 16, "Auth required", False,
                 f"upload_rejected={upload_rejected}, delete_rejected={delete_rejected}")
        return False


def test_08_extension_guard():
    """§10: archivo .txt => 400 'Only .xlsx files are supported' (pre-parseo)."""
    response, _ = upload_ar_file(filename="malformado.txt", content_type="text/plain",
                                 fileobj=b"not an excel file")
    if response is not None and response.status_code == 400:
        try:
            detail_ok = "Only .xlsx files are supported" in response.json().get("detail", "")
        except ValueError:
            detail_ok = False
        if detail_ok:
            log_test(8, 16, "Extension guard", True, "400 + mensaje exacto")
            return True
        log_test(8, 16, "Extension guard", False, f"400 pero detail inesperado: {response.text[:80]}")
        return False
    else:
        detail = response.text if response is not None else "error"
        log_test(8, 16, "Extension guard", False, f"status={getattr(response, 'status_code', None)} {detail[:80]}")
        return False


def test_09_cleanup_crud_records():
    """Limpiar registros CRUD de prueba (antes del ETL para no interferir)."""
    if not state.created_ar_ids:
        log_test(9, 16, "Cleanup CRUD records", True, "nothing to clean")
        return True

    deleted_count = 0
    for ar_id in state.created_ar_ids[:]:
        response = api_request("DELETE", f"{AR_BASE}/{ar_id}")
        if response is not None and response.status_code == 200:
            state.created_ar_ids.remove(ar_id)
            deleted_count += 1

    if deleted_count > 0 and len(state.created_ar_ids) == 0:
        log_test(9, 16, "Cleanup CRUD records", True, f"deleted {deleted_count}")
        return True
    else:
        log_test(9, 16, "Cleanup CRUD records", False,
                 f"deleted {deleted_count}, remaining {len(state.created_ar_ids)}")
        return False


def test_10_upload_etl_estado_cuenta():
    """AC-2: primera carga EstadoCuenta306090.xlsx => metricas exactas del archivo
    + metricas hibridas dependientes de BD."""
    # Pre-cleanup: eliminar registros ETL de ejecuciones anteriores
    all_rows = get_all_ar_rows()
    if all_rows is None:
        log_test(10, 16, "Upload ETL Estado de Cuenta", False, "pre-cleanup list failed")
        return False

    etl_existing = filter_etl_rows(all_rows)
    for doc in sorted(set(r["document_number"] for r in etl_existing)):
        api_request("DELETE", f"{AR_BASE}/by-document/{quote(doc)}")

    state.pre_upload_count = len(all_rows) - len(etl_existing)

    response, elapsed = upload_ar_file()
    state.upload_time = elapsed

    if response is not None and response.status_code == 200:
        data = response.json()
        details = data.get("details", {})
        mismatches = []

        def expect(label, actual, predicate):
            if not predicate:
                mismatches.append(f"{label}: got {actual}")

        # Deterministas del archivo (spec §4.1 / AC-2)
        expect("records_inserted", data.get("records_inserted"),
               lambda v: v == EXPECTED_INSERTED)
        expect("records_replaced", data.get("records_replaced"), lambda v: v == 0)
        expect("records_closed", data.get("records_closed"), lambda v: v == 0)
        expect("statement_date", data.get("statement_date"),
               lambda v: v == EXPECTED_CUTOFF)
        expect("forced", data.get("forced"), lambda v: v is False)
        expect("source_file", data.get("source_file"), lambda v: v == EXCEL_FILENAME)
        expect("total_rows_raw", details.get("total_rows_raw"), lambda v: v == EXPECTED_RAW)
        expect("rows_excluded_subtotals", details.get("rows_excluded_subtotals"),
               lambda v: v == EXPECTED_SUBTOTALS)
        expect("total_outstanding_balance", details.get("total_outstanding_balance"),
               lambda v: check_close(v, EXPECTED_SUM))
        expect("elapsed<10s", round(elapsed, 2), lambda v: elapsed < 10)

        # Hibridas: dependientes del estado de la BD dev (A-5, D-4)
        expect("legacy_debt_records>=51", details.get("legacy_debt_records"),
               lambda v: isinstance(v, int) and v >= EXPECTED_RC_DOCS)
        expect("unique_customers>0", details.get("unique_customers"),
               lambda v: isinstance(v, int) and v > 0)
        # >=1 asumiendo el contact sembrado con doc 1043635944 (AC-6/D-4)
        expect("contact_fallback>=1", details.get("contact_fallback_resolved"),
               lambda v: isinstance(v, int) and v >= 1)

        refreshed = get_all_ar_rows()
        if refreshed is not None:
            etl_rows = filter_etl_rows(refreshed)
            state.etl_docs = set(r["document_number"] for r in etl_rows)
            state.etl_balance_sum = sum(r.get("balance") or 0.0 for r in etl_rows)

        if not mismatches:
            log_test(10, 16, "Upload ETL Estado de Cuenta", True,
                     f"inserted={data.get('records_inserted')}, "
                     f"customers={details.get('unique_customers')}, "
                     f"legacy={details.get('legacy_debt_records')}, "
                     f"fallback={details.get('contact_fallback_resolved')}, "
                     f"{elapsed:.2f}s")
            return True
        else:
            log_test(10, 16, "Upload ETL Estado de Cuenta", False,
                     "; ".join(mismatches)[:200])
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(10, 16, "Upload ETL Estado de Cuenta", False, detail[:200])
        return False


def test_11_verify_row_integrity():
    """AC-3: 121 filas ETL sin nulos de FK/trazabilidad, 56 negativos, rc* legacy."""
    all_rows = get_all_ar_rows()
    if all_rows is None:
        log_test(11, 16, "Verify row integrity", False, "list failed")
        return False
    etl_rows = filter_etl_rows(all_rows)

    problems = []
    if len(etl_rows) != EXPECTED_INSERTED:
        problems.append(f"rows={len(etl_rows)} != {EXPECTED_INSERTED}")

    for field in ("id_customer", "customer_document", "identification_original",
                  "statement_date"):
        n_nulls = sum(1 for r in etl_rows if r.get(field) is None)
        if n_nulls:
            problems.append(f"{field} NULL={n_nulls}")

    n_neg = sum(1 for r in etl_rows if (r.get("total_amount") or 0) < 0)
    if n_neg != EXPECTED_NEGATIVES:
        problems.append(f"negativos={n_neg} != {EXPECTED_NEGATIVES}")

    rc_rows = [r for r in etl_rows if str(r.get("document_number", "")).startswith("rc")]
    rc_linked = [r for r in rc_rows if r.get("id_invoice") is not None]
    if len(rc_rows) != EXPECTED_RC_DOCS or rc_linked:
        problems.append(f"rc={len(rc_rows)} (exp {EXPECTED_RC_DOCS}), "
                        f"rc_con_invoice={len(rc_linked)}")

    bad_bucket = {r.get("aging_bucket") for r in etl_rows} - ALLOWED_BUCKETS
    if bad_bucket:
        problems.append(f"buckets invalidos={list(bad_bucket)[:3]}")

    bad_cutoff = {r.get("statement_date") for r in etl_rows} - {EXPECTED_CUTOFF}
    if bad_cutoff:
        problems.append(f"cortes distintos={list(bad_cutoff)[:3]}")

    if not problems:
        log_test(11, 16, "Verify row integrity", True,
                 f"{len(etl_rows)} filas, 56 negativos, {len(rc_rows)} rc legacy, "
                 "buckets/corte validos")
        return True
    else:
        log_test(11, 16, "Verify row integrity", False, "; ".join(problems)[:200])
        return False


def test_12_verify_duplicate_document():
    """AC-10: FVFE1595 => 2 filas ETL con el mismo id_invoice (A-3, min key)."""
    all_rows = get_all_ar_rows()
    if all_rows is None:
        log_test(12, 16, "Verify duplicate document", False, "list failed")
        return False
    dup_rows = [r for r in filter_etl_rows(all_rows)
                if r.get("document_number") == DUPLICATE_DOC]

    invoice_ids = {r.get("id_invoice") for r in dup_rows}
    if len(dup_rows) == 2 and len(invoice_ids) == 1:
        log_test(12, 16, "Verify duplicate document", True,
                 f"2 filas {DUPLICATE_DOC}, id_invoice={invoice_ids.pop()}")
        return True
    else:
        log_test(12, 16, "Verify duplicate document", False,
                 f"rows={len(dup_rows)}, invoice_ids={invoice_ids}")
        return False


def test_13_verify_balance_invariant():
    """AC-12: invariante total_amount == paid_amount + balance en filas ETL."""
    all_rows = get_all_ar_rows()
    if all_rows is None:
        log_test(13, 16, "Verify balance invariant", False, "list failed")
        return False
    etl_rows = filter_etl_rows(all_rows)
    if not etl_rows:
        log_test(13, 16, "Verify balance invariant", False, "no ETL rows (upload previo fallo)")
        return False
    broken = [r for r in etl_rows
              if not check_close(r.get("total_amount"),
                                 (r.get("paid_amount") or 0) + (r.get("balance") or 0))]
    not_open = [r for r in etl_rows if r.get("status") != "OPEN"]

    if not broken and not not_open:
        log_test(13, 16, "Verify balance invariant", True,
                 f"{len(etl_rows)} filas invariante OK, todas OPEN")
        return True
    else:
        log_test(13, 16, "Verify balance invariant", False,
                 f"broken={len(broken)}, not_open={len(not_open)}")
        return False


def test_14_upload_reemplazo_idempotente():
    """AC-4: recarga del mismo archivo => replaced=121, closed=0, estado identico."""
    if len(state.etl_docs) == 0:
        log_test(14, 16, "Upload reemplazo idempotente", False, "no first upload")
        return False

    response, elapsed = upload_ar_file()
    if response is not None and response.status_code == 200:
        data = response.json()
        inserted = data.get("records_inserted", 0)
        replaced = data.get("records_replaced", None)
        closed = data.get("records_closed", None)
        forced = data.get("forced", None)

        all_rows = get_all_ar_rows()
        etl_rows = filter_etl_rows(all_rows) if all_rows is not None else []
        balance_sum = sum(r.get("balance") or 0.0 for r in etl_rows)
        docs_unique = set(r["document_number"] for r in etl_rows)
        total_count = len(all_rows) if all_rows is not None else -1

        ok = (
            inserted == EXPECTED_INSERTED
            and replaced == EXPECTED_INSERTED
            and closed == 0
            and forced is False
            and len(etl_rows) == EXPECTED_INSERTED
            and len(docs_unique) == EXPECTED_DOCS_UNIQUE
            and total_count == state.pre_upload_count + EXPECTED_INSERTED
            and check_close(balance_sum, state.etl_balance_sum, tol=0.01)
        )
        if ok:
            log_test(14, 16, "Upload reemplazo idempotente", True,
                     f"inserted={inserted}, replaced={replaced}, closed={closed}, "
                     f"docs={len(docs_unique)}, {elapsed:.2f}s")
            return True
        else:
            log_test(14, 16, "Upload reemplazo idempotente", False,
                     f"inserted={inserted} (exp 121), replaced={replaced} (exp 121), "
                     f"closed={closed}, forced={forced}, etl={len(etl_rows)}, "
                     f"docs={len(docs_unique)}, total={total_count}, "
                     f"sum_diff={abs(balance_sum - state.etl_balance_sum):.4f}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(14, 16, "Upload reemplazo idempotente", False, detail[:200])
        return False


def test_15_delete_by_document():
    """AC-11: DELETE by-document FVFE1595 => records_deleted==2; inexistente => 404."""
    response = api_request("DELETE", f"{AR_BASE}/by-document/{quote(DUPLICATE_DOC)}")
    dup_ok = False
    if response is not None and response.status_code == 200:
        data = response.json()
        dup_ok = (data.get("records_deleted") == 2
                  and data.get("document_number") == DUPLICATE_DOC)

    response = api_request("DELETE", f"{AR_BASE}/by-document/{quote('ZZZ_INEXISTENTE_999')}")
    notfound_ok = response is not None and response.status_code == 404

    if dup_ok and notfound_ok:
        remaining = get_all_ar_rows()
        left = len(filter_etl_rows(remaining)) if remaining is not None else -1
        log_test(15, 16, "Delete by document", True,
                 f"{DUPLICATE_DOC}: 2 filas borradas, 404 en inexistente, etl_restantes={left}")
        return True
    else:
        log_test(15, 16, "Delete by document", False,
                 f"dup_ok={dup_ok} ({getattr(response, 'status_code', None)}), "
                 f"notfound_ok={notfound_ok}")
        return False


def test_16_cleanup_etl_records():
    """Limpiar registros ETL via DELETE by-document y verificar conteo restaurado."""
    all_rows = get_all_ar_rows()
    if all_rows is None:
        log_test(16, 16, "Cleanup ETL records", False, "list failed")
        return False

    etl_rows = filter_etl_rows(all_rows)
    docs = sorted(set(r["document_number"] for r in etl_rows))
    if not docs:
        log_test(16, 16, "Cleanup ETL records", True, "nothing to clean")
        return True

    deleted_total = 0
    for doc in docs:
        response = api_request("DELETE", f"{AR_BASE}/by-document/{quote(doc)}")
        if response is not None and response.status_code == 200:
            deleted_total += response.json().get("records_deleted", 0)

    final_rows = get_all_ar_rows()
    final_count = len(final_rows) if final_rows is not None else -1

    if deleted_total > 0 and final_count == state.pre_upload_count:
        log_test(16, 16, "Cleanup ETL records", True,
                 f"deleted {deleted_total} rows across {len(docs)} docs; "
                 f"total restaurado={final_count}")
        return True
    else:
        log_test(16, 16, "Cleanup ETL records", False,
                 f"deleted={deleted_total}, final={final_count}, "
                 f"expected={state.pre_upload_count}")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Accounts Receivable Module Smoke Tests (spec 02_08)")
    print("=" * 60)
    print(f"Base URL:    {BASE_URL}")
    print(f"User:        {USERNAME}")
    print(f"Excel file:  {AR_EXCEL_PATH}")
    print()

    tests = [
        test_01_login,
        test_02_create_account_receivable,
        test_03_get_account_receivable,
        test_04_list_and_status_filter,
        test_05_update_account_receivable,
        test_06_negative_amount_allowed,
        test_07_auth_required,
        test_08_extension_guard,
        test_09_cleanup_crud_records,
        test_10_upload_etl_estado_cuenta,
        test_11_verify_row_integrity,
        test_12_verify_duplicate_document,
        test_13_verify_balance_invariant,
        test_14_upload_reemplazo_idempotente,
        test_15_delete_by_document,
        #test_16_cleanup_etl_records,
    ]

    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"  [ERROR] {test_func.__name__}: {e}")
            state.failed += 1

    print()
    print("=" * 60)
    print(f"Results: {state.passed}/{len(tests)} passed")
    if state.upload_time:
        print(f"Upload ETL time: {state.upload_time:.2f}s")
    if state.failed > 0:
        print("Failed tests:")
        for name, success, detail in state.results:
            if not success:
                print(f"  - {name}: {detail}")
    print("=" * 60)

    if state.created_ar_ids:
        print(f"\nAR creados (para limpieza manual): {state.created_ar_ids}")

    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
