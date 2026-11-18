"""
Actual Expense Module Smoke Tests

Prueba los endpoints del módulo de actual expenses:
- CRUD individual (create, read, update, delete)
- Delete masivo por document_number
- ETL upload desde Excel (LibroAuxiliarCECO.xlsx)
- Reemplazo automático al re-cargar archivos
- Validaciones de integridad
- Limpieza de datos de prueba

Endpoints bajo prueba:
    GET    /budget/actual-expense/                        - Listar actual expenses
    GET    /budget/actual-expense/{id}                    - Obtener por ID
    POST   /budget/actual-expense/                        - Crear actual expense
    PUT    /budget/actual-expense/{id}                    - Actualizar actual expense
    DELETE /budget/actual-expense/{id}                    - Eliminar actual expense
    DELETE /budget/actual-expense/by-document/{doc_num}   - Eliminar por document_number
    POST   /budget/upload/actual-expenses                 - ETL upload LibroAuxiliarCECO.xlsx

Uso:
    1. Asegurar que .env_test existe con credenciales válidas
    2. python test_actual_expense_smoke.py
"""

import sys
import time
import requests
import pandas as pd
from pathlib import Path
from dotenv import dotenv_values

# ══════════════════════════════════════════════════════════════
# CARGAR CONFIGURACIÓN DESDE .env_test
# ══════════════════════════════════════════════════════════════

TEST_DIR = Path(__file__).parent
ENV_FILE = TEST_DIR / ".env_test"

if not ENV_FILE.exists():
    print(f"ERROR: No se encontró {ENV_FILE}")
    print(f"Crea .env_test con BASE_URL, USERNAME, PASSWORD, ACTUAL_EXPENSE_EXCEL_PATH")
    sys.exit(1)

config = dotenv_values(ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')
ACTUAL_EXPENSE_EXCEL_PATH = config.get("ACTUAL_EXPENSE_EXCEL_PATH", "").strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

if not ACTUAL_EXPENSE_EXCEL_PATH:
    print("ERROR: ACTUAL_EXPENSE_EXCEL_PATH es requerido en .env_test")
    sys.exit(1)

if not Path(ACTUAL_EXPENSE_EXCEL_PATH).exists():
    print(f"ERROR: No se encontró {ACTUAL_EXPENSE_EXCEL_PATH}")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.test_cost_center_id = None
        self.created_actual_expense_ids = []
        self.etl_inserted_count = 0
        self.etl_document_numbers = []
        self.first_upload_count = 0
        self.second_upload_count = 0
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


# ══════════════════════════════════════════════════════════════
# PRUEBAS
# ══════════════════════════════════════════════════════════════

def test_01_login():
    """Obtener JWT token para autenticación."""
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


def test_02_list_cost_centers():
    """Listar cost centers para obtener un id válido."""
    response = api_request("GET", "/budget/cost-center/?limit=5")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_cost_center_id = data[0]["id_cost_center"]
            log_test(2, 16, "List cost centers", True, f"found {len(data)}, id={state.test_cost_center_id}")
            return True
        else:
            log_test(2, 16, "List cost centers", False, "no cost centers found")
            return False
    else:
        log_test(2, 16, "List cost centers", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_03_create_actual_expense():
    """Crear un actual expense vía POST /budget/actual-expense/ con campos nuevos."""
    if not state.test_cost_center_id:
        log_test(3, 16, "Create actual expense", False, "missing cost_center_id")
        return False

    actual_expense_data = {
        "id_cost_center": state.test_cost_center_id,
        "accounting_account": "51402001",
        "expense_date": "2026-01-15",
        "expense_type": "ADUANEROS",
        "description": "Test expense description",
        "amount": 5000.00,
        "document_number": "TEST-DOC-001",
        "third_party_account": "Proveedor Test S.A.S",
        "source_file": "test_smoke"
    }

    response = api_request("POST", "/budget/actual-expense/", json=actual_expense_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        expense_id = data.get("id_actual_expense")
        accounting_account = data.get("accounting_account")
        document_number = data.get("document_number")
        state.created_actual_expense_ids.append(expense_id)
        log_test(3, 16, "Create actual expense", True, f"id={expense_id}, account={accounting_account}, doc={document_number}")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(3, 16, "Create actual expense", False, detail[:80])
        return False


def test_04_get_actual_expense():
    """Obtener un actual expense por ID vía GET /budget/actual-expense/{id}."""
    if not state.created_actual_expense_ids:
        log_test(4, 16, "Get actual expense", False, "no actual expense created")
        return False

    expense_id = state.created_actual_expense_ids[-1]
    response = api_request("GET", f"/budget/actual-expense/{expense_id}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("id_actual_expense") == expense_id:
            accounting_account = data.get("accounting_account")
            third_party = data.get("third_party_account")
            log_test(4, 16, "Get actual expense", True, f"id={expense_id}, account={accounting_account}, third_party={third_party}")
            return True
        else:
            log_test(4, 16, "Get actual expense", False, "ID mismatch")
            return False
    else:
        log_test(4, 16, "Get actual expense", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_05_list_actual_expenses():
    """Listar actual expenses vía GET /budget/actual-expense/."""
    response = api_request("GET", "/budget/actual-expense/?limit=10")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            log_test(5, 16, "List actual expenses", True, f"found {len(data)}")
            return True
        else:
            log_test(5, 16, "List actual expenses", False, "no actual expenses found")
            return False
    else:
        log_test(5, 16, "List actual expenses", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_06_update_actual_expense():
    """Actualizar un actual expense vía PUT /budget/actual-expense/{id}."""
    if not state.created_actual_expense_ids:
        log_test(6, 16, "Update actual expense", False, "no actual expense created")
        return False

    expense_id = state.created_actual_expense_ids[-1]
    update_data = {
        "id_cost_center": state.test_cost_center_id,
        "accounting_account": "52301005",
        "expense_date": "2026-01-16",
        "expense_type": "SERVICIOS",
        "description": "Updated test description",
        "amount": 7500.00,
        "document_number": "TEST-DOC-001-UPDATED",
        "third_party_account": "Proveedor Updated S.A.S",
        "source_file": "test_smoke_updated"
    }

    response = api_request("PUT", f"/budget/actual-expense/{expense_id}", json=update_data)
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("amount") == 7500.00 and data.get("expense_type") == "SERVICIOS":
            accounting_account = data.get("accounting_account")
            log_test(6, 16, "Update actual expense", True, f"amount/expense_type updated, account={accounting_account}")
            return True
        else:
            log_test(6, 16, "Update actual expense", False, "update not apply correctly")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(6, 16, "Update actual expense", False, detail[:80])
        return False


def test_07_validate_invalid_cost_center():
    """Validar que un cost_center inexistente es rechazado (404/422)."""
    actual_expense_data = {
        "id_cost_center": 999999,
        "accounting_account": "51402001",
        "expense_date": "2026-01-15",
        "expense_type": "ADUANEROS",
        "amount": 100.00,
        "document_number": "TEST-INVALID-CC",
        "source_file": "test_invalid"
    }

    response = api_request("POST", "/budget/actual-expense/", json=actual_expense_data)
    if response is not None and response.status_code in (400, 404, 422):
        log_test(7, 16, "Validate invalid cost center", True, "invalid cost center rejected")
        return True
    else:
        log_test(7, 16, "Validate invalid cost center", False, "invalid cost center not rejected")
        return False


def test_08_validate_negative_amount_allowed():
    """Validar que un amount negativo es ACEPTADO (notas de crédito)."""
    actual_expense_data = {
        "id_cost_center": state.test_cost_center_id,
        "accounting_account": "51402001",
        "expense_date": "2026-01-15",
        "expense_type": "NOTA_CREDITO",
        "amount": -500.00,
        "document_number": "TEST-NEG-AMOUNT",
        "description": "Credit note test",
        "source_file": "test_negative"
    }

    response = api_request("POST", "/budget/actual-expense/", json=actual_expense_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        expense_id = data.get("id_actual_expense")
        state.created_actual_expense_ids.append(expense_id)
        log_test(8, 16, "Validate negative amount allowed", True, f"negative amount accepted, id={expense_id}")
        return True
    else:
        log_test(8, 16, "Validate negative amount allowed", False, "negative amount rejected (should be allowed)")
        return False


def test_09_delete_actual_expense():
    """Eliminar un actual expense vía DELETE /budget/actual-expense/{id}."""
    if not state.created_actual_expense_ids:
        log_test(9, 16, "Delete actual expense", False, "no actual expense to delete")
        return False

    expense_id = state.created_actual_expense_ids[-1]
    response = api_request("DELETE", f"/budget/actual-expense/{expense_id}")
    if response is not None and response.status_code == 200:
        state.created_actual_expense_ids.remove(expense_id)
        log_test(9, 16, "Delete actual expense", True, f"id={expense_id} deleted")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(9, 16, "Delete actual expense", False, detail[:80])
        return False


def test_10_cleanup_crud_records():
    """Limpiar registros CRUD residuales de prueba."""
    if not state.created_actual_expense_ids:
        log_test(10, 16, "Cleanup CRUD records", True, "nothing to clean")
        return True

    deleted_count = 0
    for expense_id in state.created_actual_expense_ids[:]:
        response = api_request("DELETE", f"/budget/actual-expense/{expense_id}")
        if response is not None and response.status_code == 200:
            state.created_actual_expense_ids.remove(expense_id)
            deleted_count += 1

    if deleted_count > 0 or len(state.created_actual_expense_ids) == 0:
        log_test(10, 16, "Cleanup CRUD records", True, f"deleted {deleted_count}")
        return True
    else:
        log_test(10, 16, "Cleanup CRUD records", False, "some records not deleted")
        return False


def test_11_delete_by_document_number():
    """Eliminar en bloque por document_number vía DELETE /budget/actual-expense/by-document/{doc}."""
    bulk_doc_number = "TEST-BULK-001"
    records_to_create = 3

    # Pre-cleanup: eliminar registros residuales de ejecuciones anteriores
    api_request("DELETE", f"/budget/actual-expense/by-document/{bulk_doc_number}")

    # Crear 3 registros con el mismo document_number
    created_ids = []
    for i in range(records_to_create):
        actual_expense_data = {
            "id_cost_center": state.test_cost_center_id,
            "accounting_account": "51402001",
            "expense_date": "2026-01-20",
            "expense_type": "TEST-BULK",
            "amount": (i + 1) * 100.00,
            "document_number": bulk_doc_number,
            "description": f"Bulk test record {i+1}",
            "source_file": "test_bulk_delete"
        }
        response = api_request("POST", "/budget/actual-expense/", json=actual_expense_data)
        if response is not None and response.status_code in (200, 201):
            created_ids.append(response.json().get("id_actual_expense"))

    if len(created_ids) != records_to_create:
        log_test(11, 16, "Delete by document_number", False, f"created {len(created_ids)}/{records_to_create}")
        # Limpiar los que se crearon
        for expense_id in created_ids:
            api_request("DELETE", f"/budget/actual-expense/{expense_id}")
        return False

    # Eliminar por document_number
    response = api_request("DELETE", f"/budget/actual-expense/by-document/{bulk_doc_number}")
    if response is not None and response.status_code == 200:
        data = response.json()
        records_deleted = data.get("records_deleted", 0)
        if records_deleted == records_to_create:
            # Verificar que fueron eliminados (consultar por ID)
            all_gone = True
            for expense_id in created_ids:
                verify_resp = api_request("GET", f"/budget/actual-expense/{expense_id}")
                if verify_resp is not None and verify_resp.status_code == 200:
                    all_gone = False
                    break
            if all_gone:
                log_test(11, 16, "Delete by document_number", True, f"deleted {records_deleted} records")
                return True
            else:
                log_test(11, 16, "Delete by document_number", False, "some records still exist")
                return False
        else:
            log_test(11, 16, "Delete by document_number", False, f"expected {records_to_create} deleted, got {records_deleted}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(11, 16, "Delete by document_number", False, detail[:80])
        # Limpiar manualmente
        for expense_id in created_ids:
            api_request("DELETE", f"/budget/actual-expense/{expense_id}")
        return False


def test_12_upload_etl_expenses_file():
    """
    Upload ETL de LibroAuxiliarCECO.xlsx vía POST /budget/upload/actual-expenses.
    Verifica que la respuesta incluye records_replaced=0 (primera carga).
    """
    if not Path(ACTUAL_EXPENSE_EXCEL_PATH).exists():
        log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", False, f"file not found: {ACTUAL_EXPENSE_EXCEL_PATH}")
        return False

    # Calcular expected rows desde el archivo
    try:
        df = pd.read_excel(ACTUAL_EXPENSE_EXCEL_PATH, header=3)
        # Aplicar mismos filtros que el ETL
        df = df[df['NumDoc'].notna()]
        df = df[~df['CuentaContable'].astype(str).str.contains('Total', case=False, na=False)]
        df = df[df['CuentaContable'].astype(str).str.startswith('5')]
        expected_rows = len(df)
    except Exception as e:
        log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", False, f"error reading Excel: {str(e)[:50]}")
        return False

    # Pre-cleanup: eliminar registros ETL existentes para garantizar records_replaced=0
    excel_filename = Path(ACTUAL_EXPENSE_EXCEL_PATH).name
    try:
        response = api_request("GET", "/budget/actual-expense/?limit=10000")
        if response is not None and response.status_code == 200:
            existing = response.json()
            etl_docs = set(
                r["document_number"] for r in existing
                if r.get("source_file") == excel_filename
            )
            for doc_num in etl_docs:
                api_request("DELETE", f"/budget/actual-expense/by-document/{doc_num}")
    except Exception:
        pass

    with open(ACTUAL_EXPENSE_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(ACTUAL_EXPENSE_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = api_request("POST", "/budget/upload/actual-expenses", files=files)

    if response is not None and response.status_code == 200:
        data = response.json()
        records_inserted = data.get("records_inserted", 0)
        records_replaced = data.get("records_replaced", None)
        details = data.get("details", {})

        state.etl_inserted_count = records_inserted
        state.first_upload_count = records_inserted

        # Verificar campos de reemplazo
        if records_replaced is None:
            log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", False, "missing records_replaced field")
            return False

        if records_inserted == expected_rows and records_replaced == 0:
            log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", True,
                    f"inserted={records_inserted}, replaced={records_replaced}, total_processed={details.get('total_rows_processed')}")
            return True
        else:
            log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", False,
                    f"expected={expected_rows}, got={records_inserted}, replaced={records_replaced}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(12, 16, "Upload ETL LibroAuxiliarCECO.xlsx", False, detail[:80])
        return False


def test_13_verify_etl_inserted_records():
    """Verificar que los registros insertados por ETL existen en la BD."""
    if state.etl_inserted_count == 0:
        log_test(13, 16, "Verify ETL inserted records", False, "no records inserted by ETL")
        return False

    # Obtener registros para extraer document_numbers
    response = api_request("GET", f"/budget/actual-expense/?limit={state.etl_inserted_count + 100}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if len(data) >= state.etl_inserted_count:
            # Extraer document_numbers únicos de los registros ETL (source_file = nombre del archivo)
            excel_filename = Path(ACTUAL_EXPENSE_EXCEL_PATH).name
            etl_records = [r for r in data if r.get("source_file") == excel_filename]
            state.etl_document_numbers = list(set(r["document_number"] for r in etl_records))

            log_test(13, 16, "Verify ETL inserted records", True,
                    f"verified {len(etl_records)} records, {len(state.etl_document_numbers)} unique documents")
            return True
        else:
            log_test(13, 16, "Verify ETL inserted records", False,
                    f"expected {state.etl_inserted_count}, got {len(data)}")
            return False
    else:
        log_test(13, 16, "Verify ETL inserted records", False,
                f"status {response.status_code if response is not None else 'error'}")
        return False


def test_14_upload_etl_reemplazo():
    """
    Subir el mismo archivo Excel una segunda vez para probar reemplazo automático.
    Verifica que records_replaced > 0.
    """
    if state.first_upload_count == 0:
        log_test(14, 16, "Upload ETL reemplazo", False, "no first upload to replace")
        return False

    with open(ACTUAL_EXPENSE_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(ACTUAL_EXPENSE_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = api_request("POST", "/budget/upload/actual-expenses", files=files)

    if response is not None and response.status_code == 200:
        data = response.json()
        records_inserted = data.get("records_inserted", 0)
        records_replaced = data.get("records_replaced", None)

        state.second_upload_count = records_inserted

        # Verificar que hubo reemplazo
        if records_replaced is not None and records_replaced > 0:
            log_test(14, 16, "Upload ETL reemplazo", True,
                    f"replaced={records_replaced}, inserted={records_inserted}")
            return True
        else:
            log_test(14, 16, "Upload ETL reemplazo", False,
                    f"expected records_replaced > 0, got records_replaced={records_replaced}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(14, 16, "Upload ETL reemplazo", False, detail[:80])
        return False


def test_15_verify_reemplazo():
    """Verificar que después del reemplazo no hay duplicados."""
    if state.second_upload_count == 0:
        log_test(15, 16, "Verify reemplazo", False, "no second upload to verify")
        return False

    # Obtener todos los registros
    response = api_request("GET", f"/budget/actual-expense/?limit=10000")
    if response is not None and response.status_code == 200:
        data = response.json()
        excel_filename = Path(ACTUAL_EXPENSE_EXCEL_PATH).name
        etl_records = [r for r in data if r.get("source_file") == excel_filename]

        # Verificar que el total es igual al second_upload_count (no el doble)
        if len(etl_records) == state.second_upload_count:
            log_test(15, 16, "Verify reemplazo", True,
                    f"no duplicates: {len(etl_records)} records (expected {state.second_upload_count})")
            return True
        else:
            log_test(15, 16, "Verify reemplazo", False,
                    f"expected {state.second_upload_count}, got {len(etl_records)} (possible duplicates)")
            return False
    else:
        log_test(15, 16, "Verify reemplazo", False,
                f"status {response.status_code if response is not None else 'error'}")
        return False


def test_16_cleanup_etl_records():
    """Limpiar registros ETL usando delete by document_number."""
    if not state.etl_document_numbers:
        log_test(16, 16, "Cleanup ETL records", True, "nothing to clean")
        return True

    deleted_total = 0
    for doc_number in state.etl_document_numbers:
        response = api_request("DELETE", f"/budget/actual-expense/by-document/{doc_number}")
        if response is not None and response.status_code == 200:
            data = response.json()
            deleted_total += data.get("records_deleted", 0)

    if deleted_total > 0:
        log_test(16, 16, "Cleanup ETL records", True,
                f"deleted {deleted_total} records across {len(state.etl_document_numbers)} documents")
        return True
    else:
        log_test(16, 16, "Cleanup ETL records", False, "no records deleted")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Actual Expense Module Smoke Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User: {USERNAME}")
    print(f"Excel file: {ACTUAL_EXPENSE_EXCEL_PATH}")
    print()

    tests = [
        test_01_login,
        test_02_list_cost_centers,
        test_03_create_actual_expense,
        test_04_get_actual_expense,
        test_05_list_actual_expenses,
        test_06_update_actual_expense,
        test_07_validate_invalid_cost_center,
        test_08_validate_negative_amount_allowed,
        test_09_delete_actual_expense,
        test_10_cleanup_crud_records,
        test_11_delete_by_document_number,
        test_12_upload_etl_expenses_file,
        test_13_verify_etl_inserted_records,
        test_14_upload_etl_reemplazo,
        test_15_verify_reemplazo,
        test_16_cleanup_etl_records,
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
    if state.failed > 0:
        print(f"Failed tests:")
        for name, success, detail in state.results:
            if not success:
                print(f"  - {name}: {detail}")
    print("=" * 60)

    if state.created_actual_expense_ids:
        print(f"\nActual expenses creados (para limpieza manual): {state.created_actual_expense_ids}")

    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
