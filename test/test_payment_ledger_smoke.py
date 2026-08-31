"""
Payment Ledger Module Smoke Tests

Prueba los endpoints del modulo de payment ledger:
- CRUD individual (create, read, update, delete)
- Eliminar por receipt_number (by-receipt)
- ETL upload desde Excel (Recibos.xlsx)
- Reemplazo atomico idempotente por recibo
- Flag include_initial_balances (SI) y revert sin flag
- Validaciones de schema e integridad referencial
- Limpieza de datos de prueba

Endpoints bajo prueba:
    GET    /budget/payment-ledger/                          - Listar con filtros
    GET    /budget/payment-ledger/{id}                      - Obtener por ID
    GET    /budget/payment-ledger/account-receivable/{id}   - Pagos por cuenta por cobrar
    POST   /budget/payment-ledger/                          - Crear
    PUT    /budget/payment-ledger/{id}                      - Actualizar
    DELETE /budget/payment-ledger/{id}                      - Eliminar por ID
    DELETE /budget/payment-ledger/by-receipt/{receipt}      - Eliminar por receipt_number
    POST   /budget/upload/payment-ledger                    - ETL upload Recibos.xlsx

Uso:
    1. Asegurar que .env_test existe con credenciales validas y
       PAYMENT_LEDGER_EXCEL_PATH apuntando al Recibos.xlsx exportado de SIIGO
    2. python test_payment_ledger_smoke.py
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
    print(f"Crea .env_test con BASE_URL, USERNAME, PASSWORD, PAYMENT_LEDGER_EXCEL_PATH")
    sys.exit(1)

config = dotenv_values(ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')
PAYMENT_LEDGER_EXCEL_PATH = config.get("PAYMENT_LEDGER_EXCEL_PATH", "").strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

if not PAYMENT_LEDGER_EXCEL_PATH:
    print("ERROR: PAYMENT_LEDGER_EXCEL_PATH es requerido en .env_test")
    sys.exit(1)

if not Path(PAYMENT_LEDGER_EXCEL_PATH).exists():
    print(f"ERROR: No se encontro {PAYMENT_LEDGER_EXCEL_PATH}")
    sys.exit(1)

EXCEL_FILENAME = Path(PAYMENT_LEDGER_EXCEL_PATH).name

# Premisas del archivo Recibos.xlsx de SIIGO (spec backend.02_07 §6/checklist)
EXPECTED_INSERTED = 419
EXPECTED_INSERTED_WITH_SI = 439
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.created_payment_ledger_ids = []
        self.pre_upload_count = 0
        self.etl_inserted_count = 0
        self.etl_receipts = set()
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


def api_request(method: str, endpoint: str, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.request(method, url, headers=state.headers, timeout=30, **kwargs)
        return response
    except Exception as e:
        print(f"  [ERROR] Request exception: {type(e).__name__}: {str(e)[:100]}")
        return None


def get_all_ledger_rows():
    """Traer todos los registros (limite alto) para conteos client-side."""
    response = api_request("GET", "/budget/payment-ledger/?limit=10000")
    if response is not None and response.status_code == 200:
        return response.json()
    return None


def filter_etl_rows(all_rows):
    """Registros cuyo source_file == nombre del archivo Subido."""
    return [r for r in all_rows if r.get("source_file") == EXCEL_FILENAME]


def upload_payment_ledger_file(include_si: bool = False):
    """Subir el archivo multipart (SOLO campo file + flag opcional) y medir tiempo."""
    data = {"include_initial_balances": "true"} if include_si else None
    with open(PAYMENT_LEDGER_EXCEL_PATH, "rb") as f:
        files = {"file": (EXCEL_FILENAME, f, XLSX_MIME)}
        t0 = time.time()
        response = api_request(
            "POST", "/budget/upload/payment-ledger", files=files, data=data
        )
        elapsed = time.time() - t0
    return response, elapsed


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
        log_test(1, 17, "Login", True, "JWT obtenido")
        return True
    else:
        detail = response.text if response is not None else "Connection error"
        log_test(1, 17, "Login", False, detail[:50])
        return False


def test_02_create_payment_ledger():
    """Crear un registro minimo valido (sin FKs) via POST /budget/payment-ledger/."""
    payment_data = {
        "receipt_number": "TESTPL001",
        "transaction_nature": "CASH",
        "cash_flow": "in",
        "payment_date": "2026-01-15",
        "payment_amount": 1500.00,
        "accounting_account": "111001",
        "description": "Smoke test record",
        "third_party": "CUSTOMER TEST S.A.S",
        "source_file": "test_smoke",
    }

    response = api_request("POST", "/budget/payment-ledger/", json=payment_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        payment_id = data.get("id_payment_ledger")
        receipt_number = data.get("receipt_number")
        state.created_payment_ledger_ids.append(payment_id)
        log_test(2, 17, "Create payment ledger", True,
                 f"id={payment_id}, receipt={receipt_number}")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(2, 17, "Create payment ledger", False, detail[:80])
        return False


def test_03_get_payment_ledger():
    """Obtener por ID via GET /budget/payment-ledger/{id}: coincide id y receipt_number."""
    if not state.created_payment_ledger_ids:
        log_test(3, 17, "Get payment ledger", False, "no record created")
        return False

    payment_id = state.created_payment_ledger_ids[-1]
    response = api_request("GET", f"/budget/payment-ledger/{payment_id}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if (data.get("id_payment_ledger") == payment_id
                and data.get("receipt_number") == "TESTPL001"):
            log_test(3, 17, "Get payment ledger", True,
                     f"id={payment_id}, receipt={data.get('receipt_number')}")
            return True
        else:
            log_test(3, 17, "Get payment ledger", False, "id/receipt mismatch")
            return False
    else:
        log_test(3, 17, "Get payment ledger", False,
                 f"status {response.status_code if response is not None else 'error'}")
        return False


def test_04_list_payment_ledger():
    """Listar via GET /budget/payment-ledger/?limit=10 (no vacio tras el create)."""
    response = api_request("GET", "/budget/payment-ledger/?limit=10")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            log_test(4, 17, "List payment ledger", True, f"found {len(data)}")
            return True
        else:
            log_test(4, 17, "List payment ledger", False, "empty list")
            return False
    else:
        log_test(4, 17, "List payment ledger", False,
                 f"status {response.status_code if response is not None else 'error'}")
        return False


def test_05_update_payment_ledger():
    """Actualizar via PUT /budget/payment-ledger/{id} (amount/cash_flow/description)."""
    if not state.created_payment_ledger_ids:
        log_test(5, 17, "Update payment ledger", False, "no record to update")
        return False

    payment_id = state.created_payment_ledger_ids[-1]
    update_data = {
        "receipt_number": "TESTPL001",
        "transaction_nature": "CASH",
        "cash_flow": "out",
        "payment_date": "2026-01-15",
        "payment_amount": 2750.50,
        "accounting_account": "111001",
        "description": "Smoke test record updated",
        "third_party": "CUSTOMER TEST S.A.S",
        "source_file": "test_smoke",
    }

    response = api_request("PUT", f"/budget/payment-ledger/{payment_id}", json=update_data)
    if response is not None and response.status_code == 200:
        data = response.json()
        if (check_close(data.get("payment_amount"), 2750.50)
                and data.get("cash_flow") == "out"
                and data.get("description") == "Smoke test record updated"):
            log_test(5, 17, "Update payment ledger", True,
                     "amount/cash_flow/description updated")
            return True
        else:
            log_test(5, 17, "Update payment ledger", False, "update not applied correctly")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(5, 17, "Update payment ledger", False, detail[:80])
        return False


def test_06_invalid_nature_rejected():
    """Validar rechazos por schema (422): transaction_nature='PENDING' y receipt sucio."""
    payment_data = {
        "receipt_number": "TESTPLBADNATURE",
        "transaction_nature": "PENDING",
        "cash_flow": "in",
        "payment_date": "2026-01-15",
        "payment_amount": 100.00,
        "accounting_account": "111001",
        "source_file": "test_invalid",
    }

    response = api_request("POST", "/budget/payment-ledger/", json=payment_data)
    nature_rejected = response is not None and response.status_code == 422

    dirty_data = dict(payment_data, transaction_nature="CASH",
                      receipt_number="RC - 3017!")
    response = api_request("POST", "/budget/payment-ledger/", json=dirty_data)
    dirty_rejected = response is not None and response.status_code == 422

    if nature_rejected and dirty_rejected:
        log_test(6, 17, "Invalid nature rejected", True,
                 "422 pattern violation (nature + receipt sucio)")
        return True
    else:
        log_test(6, 17, "Invalid nature rejected", False,
                 f"nature_rejected={nature_rejected}, dirty_rejected={dirty_rejected}")
        return False


def test_07_negative_amount_allowed():
    """Validar monto negativo aceptado (regla D4: schema sin ge=0) con cash_flow null."""
    payment_data = {
        "receipt_number": "TESTPL002",
        "transaction_nature": "NON_CASH_ADJUSTMENT",
        "cash_flow": None,
        "payment_date": "2026-02-10",
        "payment_amount": -500.00,
        "accounting_account": "571001",
        "description": "Negative adjustment smoke test",
        "source_file": "test_smoke",
    }

    response = api_request("POST", "/budget/payment-ledger/", json=payment_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        payment_id = data.get("id_payment_ledger")
        state.created_payment_ledger_ids.append(payment_id)
        if check_close(data.get("payment_amount"), -500.00) and data.get("cash_flow") is None:
            log_test(7, 17, "Negative amount allowed", True,
                     f"negative accepted, id={payment_id}")
            return True
        else:
            log_test(7, 17, "Negative amount allowed", False,
                     "created but amount/cash_flow not as expected")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(7, 17, "Negative amount allowed", False,
                 f"negative rejected: {detail[:80]}")
        return False


def test_08_invalid_invoice_fk_rejected():
    """Validar que id_invoice inexistente es rechazado (404) por el endpoint."""
    payment_data = {
        "receipt_number": "TESTPL003",
        "transaction_nature": "CASH",
        "cash_flow": "in",
        "payment_date": "2026-01-15",
        "payment_amount": 100.00,
        "accounting_account": "111001",
        "id_invoice": 999999,
        "source_file": "test_invalid",
    }

    response = api_request("POST", "/budget/payment-ledger/", json=payment_data)
    if response is not None and response.status_code == 404:
        log_test(8, 17, "Invalid invoice FK rejected", True, "404 Invoice 999999")
        return True
    else:
        detail = f"status {response.status_code if response is not None else 'error'}"
        log_test(8, 17, "Invalid invoice FK rejected", False,
                 f"invalid FK not rejected: {detail}")
        return False


def test_09_account_receivable_endpoint():
    """GET /budget/payment-ledger/account-receivable/1 responde 200 (lista, possibly vacia)."""
    response = api_request("GET", "/budget/payment-ledger/account-receivable/1")
    if response is not None and response.status_code == 200:
        data = response.json()
        if isinstance(data, list):
            log_test(9, 17, "Account-receivable endpoint", True, f"{len(data)} payments")
            return True
        else:
            log_test(9, 17, "Account-receivable endpoint", False, "response not a list")
            return False
    else:
        log_test(9, 17, "Account-receivable endpoint", False,
                 f"status {response.status_code if response is not None else 'error'}")
        return False


def test_10_cleanup_crud_records():
    """Limpiar registros CRUD residuales de prueba (tests 2, 5, 7)."""
    if not state.created_payment_ledger_ids:
        log_test(10, 17, "Cleanup CRUD records", True, "nothing to clean")
        return True

    deleted_count = 0
    for payment_id in state.created_payment_ledger_ids[:]:
        response = api_request("DELETE", f"/budget/payment-ledger/{payment_id}")
        if response is not None and response.status_code == 200:
            state.created_payment_ledger_ids.remove(payment_id)
            deleted_count += 1

    if deleted_count > 0 and len(state.created_payment_ledger_ids) == 0:
        log_test(10, 17, "Cleanup CRUD records", True, f"deleted {deleted_count}")
        return True
    else:
        log_test(10, 17, "Cleanup CRUD records", False,
                 f"deleted {deleted_count}, remaining {len(state.created_payment_ledger_ids)}")
        return False


def test_11_upload_etl_recibos():
    """
    Upload ETL de Recibos.xlsx via POST /budget/upload/payment-ledger.
    Pre-cleanup por receipt, primera carga: records_replaced=0, inserted=419,
    detalles de control segun spec y elapsed < 10s.
    """
    if not Path(PAYMENT_LEDGER_EXCEL_PATH).exists():
        log_test(11, 17, "Upload ETL Recibos.xlsx", False,
                 f"file not found: {PAYMENT_LEDGER_EXCEL_PATH}")
        return False

    # Pre-cleanup: eliminar registros ETL de ejecuciones anteriores
    all_rows = get_all_ledger_rows()
    if all_rows is None:
        log_test(11, 17, "Upload ETL Recibos.xlsx", False, "pre-cleanup list failed")
        return False

    etl_existing = filter_etl_rows(all_rows)
    for receipt in sorted(set(r["receipt_number"] for r in etl_existing)):
        api_request("DELETE", f"/budget/payment-ledger/by-receipt/{quote(receipt)}")

    state.pre_upload_count = len(all_rows) - len(etl_existing)

    response, elapsed = upload_payment_ledger_file(include_si=False)
    state.upload_time = elapsed

    if response is not None and response.status_code == 200:
        data = response.json()
        details = data.get("details", {})
        mismatches = []

        def expect(label, actual, predicate):
            if not predicate:
                mismatches.append(f"{label}: got {actual}")

        expect("records_inserted", data.get("records_inserted"),
               lambda v: v == EXPECTED_INSERTED)
        expect("records_replaced", data.get("records_replaced"),
               lambda v: v == 0)
        expect("include_initial_balances", data.get("include_initial_balances"),
               lambda v: v is False)
        expect("total_rows_processed", details.get("total_rows_processed"),
               lambda v: v == 1418)
        expect("rows_excluded_totals", details.get("rows_excluded_totals"),
               lambda v: v == 644)
        expect("rows_excluded_documents", details.get("rows_excluded_documents"),
               lambda v: v == 335)
        expect("rows_excluded_initial_balances", details.get("rows_excluded_initial_balances"),
               lambda v: v == 20)
        expect("cash_records", details.get("cash_records"), lambda v: v == 197)
        expect("non_cash_records", details.get("non_cash_records"), lambda v: v == 222)
        expect("cash_in_count", details.get("cash_in_count"), lambda v: v == 116)
        expect("cash_out_count", details.get("cash_out_count"), lambda v: v == 81)
        expect("total_cash_in", details.get("total_cash_in"),
               lambda v: check_close(v, 508861452.00))
        expect("total_cash_out", details.get("total_cash_out"),
               lambda v: check_close(v, -367856681.92))
        expect("net_liquidity", details.get("net_liquidity"),
               lambda v: check_close(v, 141004770.08))
        expect("total_non_cash_adjustments", details.get("total_non_cash_adjustments"),
               lambda v: check_close(v, 379589107.24))
        expect("rows_with_document_candidate", details.get("rows_with_document_candidate"),
               lambda v: v == 79)
        expect("imputed+not_imputed", (details.get("invoices_imputed") or 0)
               + (details.get("documents_not_imputed") or 0),
               lambda v: v == 79)
        expect("elapsed<10s", round(elapsed, 2), lambda v: elapsed < 10)

        # Estado para verificaciones posteriores
        state.etl_inserted_count = data.get("records_inserted", 0)
        refreshed = get_all_ledger_rows()
        if refreshed is not None:
            state.etl_receipts = set(
                r["receipt_number"] for r in filter_etl_rows(refreshed)
            )

        if not mismatches:
            log_test(11, 17, "Upload ETL Recibos.xlsx", True,
                     f"inserted={state.etl_inserted_count}, replaced=0, "
                     f"receipts={len(state.etl_receipts)}, {elapsed:.2f}s")
            return True
        else:
            log_test(11, 17, "Upload ETL Recibos.xlsx", False,
                     "; ".join(mismatches)[:180])
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(11, 17, "Upload ETL Recibos.xlsx", False, detail[:180])
        return False


def test_12_verify_receipt_normalization():
    """GET ?receipt_number=RC3017: 5 filas y todos los receipts ETL alfanumericos puros."""
    response = api_request("GET", "/budget/payment-ledger/?receipt_number=RC3017&limit=100")
    if response is not None and response.status_code == 200:
        data = response.json()
        all_match = all(r.get("receipt_number") == "RC3017" for r in data)
        dirty = [rc for rc in state.etl_receipts if not rc.isalnum()]
        if len(data) == 5 and all_match and not dirty:
            log_test(12, 17, "Verify receipt normalization", True,
                     "5 filas 'RC3017'; 0 receipts con espacios/especiales")
            return True
        else:
            log_test(12, 17, "Verify receipt normalization", False,
                     f"rows={len(data)}, all_match={all_match}, dirty={dirty[:3]}")
            return False
    else:
        log_test(12, 17, "Verify receipt normalization", False,
                 f"status {response.status_code if response is not None else 'error'}")
        return False


def test_13_verify_filters():
    """Filtros server-side: nature, cash_flow, third_party (ilike), rango de fechas."""
    problems = []

    response = api_request("GET", "/budget/payment-ledger/?transaction_nature=CASH&cash_flow=in&limit=1000")
    if response is None or response.status_code != 200 or len(response.json()) != 116:
        problems.append(f"CASH&in: got {len(response.json()) if response is not None and response.status_code == 200 else response.status_code if response is not None else 'error'}, expected 116")

    response = api_request("GET", "/budget/payment-ledger/?transaction_nature=NON_CASH_ADJUSTMENT&limit=1000")
    if response is None or response.status_code != 200 or len(response.json()) != 222:
        problems.append(f"NON_CASH: got {len(response.json()) if response is not None and response.status_code == 200 else response.status_code if response is not None else 'error'}, expected 222")

    # Palabra real de third_party tomada de los registros ETL subidos
    all_rows = get_all_ledger_rows()
    etl_rows = filter_etl_rows(all_rows) if all_rows is not None else []
    tp = next((r["third_party"] for r in etl_rows if r.get("third_party")), None)
    if tp is None:
        problems.append("no third_party found in ETL rows")
    else:
        word = tp.split()[0]
        response = api_request("GET", f"/budget/payment-ledger/?third_party={quote(word)}&limit=1000")
        if response is None or response.status_code != 200:
            problems.append(f"third_party({word}): request failed")
        else:
            data = response.json()
            contains_all = all(
                word.lower() in (r.get("third_party") or "").lower() for r in data
            )
            if len(data) < 1 or not contains_all:
                problems.append(f"third_party({word}): rows={len(data)}, all_match={contains_all}")

    response = api_request("GET", "/budget/payment-ledger/?date_ge=2026-01-01&date_le=2026-12-31&limit=1000")
    if response is None or response.status_code != 200:
        problems.append("date range: request failed")
    else:
        data = response.json()
        in_range = all("2026-01-01" <= r["payment_date"] <= "2026-12-31" for r in data)
        if not in_range:
            problems.append(f"date range: {sum(1 for r in data if not ('2026-01-01' <= r['payment_date'] <= '2026-12-31'))} fuera de rango")

    if not problems:
        log_test(13, 17, "Verify filters", True,
                 f"nature/flow/third_party/dates OK ({len(etl_rows)} etl rows)")
        return True
    else:
        log_test(13, 17, "Verify filters", False, "; ".join(problems)[:180])
        return False


def test_14_upload_reemplazo_idempotente():
    """Re-subir mismo archivo (sin flag): inserted=419, replaced=419, sin duplicados."""
    if state.etl_inserted_count == 0:
        log_test(14, 17, "Upload reemplazo idempotente", False, "no first upload")
        return False

    response, elapsed = upload_payment_ledger_file(include_si=False)
    if response is not None and response.status_code == 200:
        data = response.json()
        inserted = data.get("records_inserted", 0)
        replaced = data.get("records_replaced", None)

        all_rows = get_all_ledger_rows()
        etl_rows = filter_etl_rows(all_rows) if all_rows is not None else []
        total_count = len(all_rows) if all_rows is not None else -1

        ok = (
            inserted == EXPECTED_INSERTED
            and replaced == EXPECTED_INSERTED
            and len(etl_rows) == EXPECTED_INSERTED
            and total_count == state.pre_upload_count + EXPECTED_INSERTED
        )
        if ok:
            log_test(14, 17, "Upload reemplazo idempotente", True,
                     f"inserted={inserted}, replaced={replaced}, "
                     f"total={total_count}, {elapsed:.2f}s")
            return True
        else:
            log_test(14, 17, "Upload reemplazo idempotente", False,
                     f"inserted={inserted}, replaced={replaced}, "
                     f"etl_rows={len(etl_rows)}, total={total_count}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(14, 17, "Upload reemplazo idempotente", False, detail[:80])
        return False


def test_15_upload_include_initial_balances():
    """Upload con include_initial_balances=true: 439 filas, 20 SI con cash_flow NULL."""
    response, elapsed = upload_payment_ledger_file(include_si=True)
    if response is not None and response.status_code == 200:
        data = response.json()
        details = data.get("details", {})
        mismatches = []

        if data.get("records_inserted") != EXPECTED_INSERTED_WITH_SI:
            mismatches.append(f"inserted={data.get('records_inserted')} != 439")
        if details.get("rows_excluded_initial_balances") != 0:
            mismatches.append(f"excluded_si={details.get('rows_excluded_initial_balances')} != 0")
        if details.get("non_cash_records") != 242:
            mismatches.append(f"non_cash={details.get('non_cash_records')} != 242")

        all_rows = get_all_ledger_rows()
        etl_rows = filter_etl_rows(all_rows) if all_rows is not None else []
        if len(etl_rows) != EXPECTED_INSERTED_WITH_SI:
            mismatches.append(f"etl_rows={len(etl_rows)} != 439")

        response = api_request("GET", "/budget/payment-ledger/?transaction_nature=NON_CASH_ADJUSTMENT&limit=1000")
        if response is None or response.status_code != 200:
            mismatches.append("NON_CASH query failed")
        else:
            non_cash = response.json()
            if len(non_cash) != 242:
                mismatches.append(f"non_cash_query={len(non_cash)} != 242")
            si_rows = [r for r in non_cash if str(r.get("receipt_number", "")).startswith("SI")]
            if len(si_rows) != 20:
                mismatches.append(f"si_rows={len(si_rows)} != 20")
            if any(r.get("cash_flow") is not None for r in si_rows):
                mismatches.append("some SI row has cash_flow != NULL")

        if not mismatches:
            log_test(15, 17, "Upload include_initial_balances", True,
                     f"inserted=439, SI=20 (cash_flow NULL), {elapsed:.2f}s")
            return True
        else:
            log_test(15, 17, "Upload include_initial_balances", False,
                     "; ".join(mismatches)[:180])
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(15, 17, "Upload include_initial_balances", False, detail[:80])
        return False


def test_16_revert_initial_balances():
    """Re-subir SIN flag tras la carga con SI: replaced=439 (revert completo), total=419."""
    response, elapsed = upload_payment_ledger_file(include_si=False)
    if response is not None and response.status_code == 200:
        data = response.json()
        inserted = data.get("records_inserted", 0)
        replaced = data.get("records_replaced", None)

        all_rows = get_all_ledger_rows()
        etl_rows = filter_etl_rows(all_rows) if all_rows is not None else []

        ok = (
            inserted == EXPECTED_INSERTED
            and replaced == EXPECTED_INSERTED_WITH_SI
            and len(etl_rows) == EXPECTED_INSERTED
        )
        if ok:
            log_test(16, 17, "Revert initial balances", True,
                     f"inserted={inserted}, replaced={replaced}, "
                     f"etl_rows={len(etl_rows)}, {elapsed:.2f}s")
            return True
        else:
            log_test(16, 17, "Revert initial balances", False,
                     f"inserted={inserted} (exp 419), replaced={replaced} (exp 439), "
                     f"etl_rows={len(etl_rows)} (exp 419)")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(16, 17, "Revert initial balances", False, detail[:80])
        return False


def test_17_cleanup_etl_records():
    """Limpiar registros ETL via DELETE by-receipt y verificar conteo restaurado."""
    all_rows = get_all_ledger_rows()
    if all_rows is None:
        log_test(17, 17, "Cleanup ETL records", False, "list failed")
        return False

    etl_rows = filter_etl_rows(all_rows)
    receipts = sorted(set(r["receipt_number"] for r in etl_rows))
    if not receipts:
        log_test(17, 17, "Cleanup ETL records", True, "nothing to clean")
        return True

    deleted_total = 0
    for receipt in receipts:
        response = api_request("DELETE", f"/budget/payment-ledger/by-receipt/{quote(receipt)}")
        if response is not None and response.status_code == 200:
            deleted_total += response.json().get("records_deleted", 0)

    final_rows = get_all_ledger_rows()
    final_count = len(final_rows) if final_rows is not None else -1

    if deleted_total > 0 and final_count == state.pre_upload_count:
        log_test(17, 17, "Cleanup ETL records", True,
                 f"deleted {deleted_total} rows across {len(receipts)} receipts; "
                 f"total restaurado={final_count}")
        return True
    else:
        log_test(17, 17, "Cleanup ETL records", False,
                 f"deleted={deleted_total}, final={final_count}, "
                 f"expected={state.pre_upload_count}")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Payment Ledger Module Smoke Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User: {USERNAME}")
    print(f"Excel file: {PAYMENT_LEDGER_EXCEL_PATH}")
    print()

    tests = [
        test_01_login,
        test_02_create_payment_ledger,
        test_03_get_payment_ledger,
        test_04_list_payment_ledger,
        test_05_update_payment_ledger,
        test_06_invalid_nature_rejected,
        test_07_negative_amount_allowed,
        test_08_invalid_invoice_fk_rejected,
        test_09_account_receivable_endpoint,
        test_10_cleanup_crud_records,
        test_11_upload_etl_recibos,
        test_12_verify_receipt_normalization,
        test_13_verify_filters,
        test_14_upload_reemplazo_idempotente,
        test_15_upload_include_initial_balances,
        test_16_revert_initial_balances,
        #test_17_cleanup_etl_records,
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
        print(f"Failed tests:")
        for name, success, detail in state.results:
            if not success:
                print(f"  - {name}: {detail}")
    print("=" * 60)

    if state.created_payment_ledger_ids:
        print(f"\nPayment ledger creados (para limpieza manual): {state.created_payment_ledger_ids}")

    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
