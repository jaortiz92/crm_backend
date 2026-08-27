"""
Actual Cost Module Smoke Tests

Prueba los endpoints del módulo de actual costs:
- CRUD individual (create, read, update, delete)
- Delete masivo por document_number
- ETL upload desde Excel (Costos.xlsx)
- Reemplazo automático al re-cargar archivos
- Validaciones de integridad
- Limpieza de datos de prueba

Endpoints bajo prueba:
    GET    /budget/actual-cost/                        - Listar actual costs
    GET    /budget/actual-cost/{id}                    - Obtener por ID
    POST   /budget/actual-cost/                        - Crear actual cost
    PUT    /budget/actual-cost/{id}                    - Actualizar actual cost
    DELETE /budget/actual-cost/{id}                    - Eliminar actual cost
    DELETE /budget/actual-cost/by-document/{doc_num}   - Eliminar por document_number
    POST   /budget/upload/actual-costs                 - ETL upload Costos.xlsx

Uso:
    1. Asegurar que .env_test existe con credenciales válidas
    2. python test_actual_cost_smoke.py
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
    print(f"Crea .env_test con BASE_URL, USERNAME, PASSWORD, COST_EXCEL_PATH")
    sys.exit(1)

config = dotenv_values(ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')
COST_EXCEL_PATH = config.get("COST_EXCEL_PATH", "").strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

if not COST_EXCEL_PATH:
    print("ERROR: COST_EXCEL_PATH es requerido en .env_test")
    sys.exit(1)

if not Path(COST_EXCEL_PATH).exists():
    print(f"ERROR: No se encontró {COST_EXCEL_PATH}")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.test_cost_center_id = None
        self.test_reference_id = None
        self.created_actual_cost_ids = []
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
        log_test(1, 17, "Login", True, "JWT obtenido")
        return True
    else:
        detail = response.text if response is not None else "Connection error"
        log_test(1, 17, "Login", False, detail[:50])
        return False


def test_02_list_cost_centers():
    """Listar cost centers para obtener un id válido."""
    response = api_request("GET", "/budget/cost-center/?limit=5")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_cost_center_id = data[0]["id_cost_center"]
            log_test(2, 17, "List cost centers", True, f"found {len(data)}, id={state.test_cost_center_id}")
            return True
        else:
            log_test(2, 17, "List cost centers", False, "no cost centers found")
            return False
    else:
        log_test(2, 17, "List cost centers", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_03_list_references():
    """Listar referencias para obtener un id válido."""
    response = api_request("GET", "/reference/?limit=5")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_reference_id = data[0]["id_reference"]
            log_test(3, 17, "List references", True, f"found {len(data)}, id={state.test_reference_id}")
            return True
        else:
            log_test(3, 17, "List references", False, "no references found")
            return False
    else:
        log_test(3, 17, "List references", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_04_create_actual_cost():
    """Crear un actual cost vía POST /budget/actual-cost/ con description."""
    if not state.test_cost_center_id or not state.test_reference_id:
        log_test(4, 17, "Create actual cost", False, "missing cost_center_id or reference_id")
        return False

    actual_cost_data = {
        "id_cost_center": state.test_cost_center_id,
        "document_number": "TEST-DOC-001",
        "id_reference": state.test_reference_id,
        "quantity": 5,
        "unit_cost": 1000.00,
        "cost_date": "2026-01-15",
        "cost_type": "test",
        "amount": 5000.00,
        "description": "Test cost description",
        "source_file": "test_smoke"
    }

    response = api_request("POST", "/budget/actual-cost/", json=actual_cost_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        cost_id = data.get("id_actual_cost")
        description = data.get("description")
        state.created_actual_cost_ids.append(cost_id)
        log_test(4, 17, "Create actual cost", True, f"id={cost_id}, description='{description}'")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(4, 17, "Create actual cost", False, detail[:80])
        return False


def test_05_get_actual_cost():
    """Obtener un actual cost por ID vía GET /budget/actual-cost/{id}."""
    if not state.created_actual_cost_ids:
        log_test(5, 17, "Get actual cost", False, "no actual cost created")
        return False

    cost_id = state.created_actual_cost_ids[-1]
    response = api_request("GET", f"/budget/actual-cost/{cost_id}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("id_actual_cost") == cost_id:
            description = data.get("description")
            log_test(5, 17, "Get actual cost", True, f"id={cost_id}, description='{description}'")
            return True
        else:
            log_test(5, 17, "Get actual cost", False, "ID mismatch")
            return False
    else:
        log_test(5, 17, "Get actual cost", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_06_list_actual_costs():
    """Listar actual costs vía GET /budget/actual-cost/."""
    response = api_request("GET", "/budget/actual-cost/?limit=10")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            log_test(6, 17, "List actual costs", True, f"found {len(data)}")
            return True
        else:
            log_test(6, 17, "List actual costs", False, "no actual costs found")
            return False
    else:
        log_test(6, 17, "List actual costs", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_07_update_actual_cost():
    """Actualizar un actual cost vía PUT /budget/actual-cost/{id} con description."""
    if not state.created_actual_cost_ids:
        log_test(7, 17, "Update actual cost", False, "no actual cost created")
        return False

    cost_id = state.created_actual_cost_ids[-1]
    update_data = {
        "id_cost_center": state.test_cost_center_id,
        "document_number": "TEST-DOC-001-UPDATED",
        "id_reference": state.test_reference_id,
        "quantity": 10,
        "unit_cost": 2000.00,
        "cost_date": "2026-01-16",
        "cost_type": "test-updated",
        "amount": 20000.00,
        "description": "Updated test description",
        "source_file": "test_smoke_updated"
    }

    response = api_request("PUT", f"/budget/actual-cost/{cost_id}", json=update_data)
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("quantity") == 10 and data.get("unit_cost") == 2000.00:
            description = data.get("description")
            log_test(7, 17, "Update actual cost", True, f"quantity/unit_cost updated, description='{description}'")
            return True
        else:
            log_test(7, 17, "Update actual cost", False, "update not apply correctly")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(7, 17, "Update actual cost", False, detail[:80])
        return False


def test_08_validate_invalid_cost_center():
    """Validar que un cost_center inexistente es rechazado (404/422)."""
    actual_cost_data = {
        "id_cost_center": 999999,
        "document_number": "TEST-INVALID-CC",
        "id_reference": state.test_reference_id if state.test_reference_id else 1,
        "quantity": 1,
        "unit_cost": 100.00,
        "cost_date": "2026-01-15",
        "cost_type": "test",
        "amount": 100.00,
        "source_file": "test_invalid"
    }

    response = api_request("POST", "/budget/actual-cost/", json=actual_cost_data)
    if response is not None and response.status_code in (400, 404, 422):
        log_test(8, 17, "Validate invalid cost center", True, "invalid cost center rejected")
        return True
    else:
        log_test(8, 17, "Validate invalid cost center", False, "invalid cost center not rejected")
        return False


def test_09_validate_negative_quantity():
    """Validar que una cantidad negativa es rechazada (422 por Pydantic ge=0)."""
    actual_cost_data = {
        "id_cost_center": state.test_cost_center_id,
        "document_number": "TEST-NEG-QTY",
        "id_reference": state.test_reference_id if state.test_reference_id else 1,
        "quantity": -5,
        "unit_cost": 100.00,
        "cost_date": "2026-01-15",
        "cost_type": "test",
        "amount": -500.00,
        "source_file": "test_invalid"
    }

    response = api_request("POST", "/budget/actual-cost/", json=actual_cost_data)
    if response is not None and response.status_code in (400, 422):
        log_test(9, 17, "Validate negative quantity", True, "negative quantity rejected")
        return True
    else:
        log_test(9, 17, "Validate negative quantity", False, "negative quantity not rejected")
        return False


def test_10_delete_actual_cost():
    """Eliminar un actual cost vía DELETE /budget/actual-cost/{id}."""
    if not state.created_actual_cost_ids:
        log_test(10, 17, "Delete actual cost", False, "no actual cost to delete")
        return False

    cost_id = state.created_actual_cost_ids[-1]
    response = api_request("DELETE", f"/budget/actual-cost/{cost_id}")
    if response is not None and response.status_code == 200:
        state.created_actual_cost_ids.remove(cost_id)
        log_test(10, 17, "Delete actual cost", True, f"id={cost_id} deleted")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(10, 17, "Delete actual cost", False, detail[:80])
        return False


def test_11_cleanup_crud_records():
    """Limpiar registros CRUD residuales de prueba."""
    if not state.created_actual_cost_ids:
        log_test(11, 17, "Cleanup CRUD records", True, "nothing to clean")
        return True

    deleted_count = 0
    for cost_id in state.created_actual_cost_ids[:]:
        response = api_request("DELETE", f"/budget/actual-cost/{cost_id}")
        if response is not None and response.status_code == 200:
            state.created_actual_cost_ids.remove(cost_id)
            deleted_count += 1

    if deleted_count > 0 or len(state.created_actual_cost_ids) == 0:
        log_test(11, 17, "Cleanup CRUD records", True, f"deleted {deleted_count}")
        return True
    else:
        log_test(11, 17, "Cleanup CRUD records", False, "some records not deleted")
        return False


def test_12_delete_by_document_number():
    """Eliminar en bloque por document_number vía DELETE /budget/actual-cost/by-document/{doc}."""
    bulk_doc_number = "TEST-BULK-001"
    records_to_create = 3

    # Pre-cleanup: eliminar registros residuales de ejecuciones anteriores
    api_request("DELETE", f"/budget/actual-cost/by-document/{bulk_doc_number}")

    # Crear 3 registros con el mismo document_number
    created_ids = []
    for i in range(records_to_create):
        actual_cost_data = {
            "id_cost_center": state.test_cost_center_id,
            "document_number": bulk_doc_number,
            "id_reference": state.test_reference_id,
            "quantity": i + 1,
            "unit_cost": 100.00,
            "cost_date": "2026-01-20",
            "cost_type": "test-bulk",
            "amount": (i + 1) * 100.00,
            "description": f"Bulk test record {i+1}",
            "source_file": "test_bulk_delete"
        }
        response = api_request("POST", "/budget/actual-cost/", json=actual_cost_data)
        if response is not None and response.status_code in (200, 201):
            created_ids.append(response.json().get("id_actual_cost"))

    if len(created_ids) != records_to_create:
        log_test(12, 17, "Delete by document_number", False, f"created {len(created_ids)}/{records_to_create}")
        # Limpiar los que se crearon
        for cost_id in created_ids:
            api_request("DELETE", f"/budget/actual-cost/{cost_id}")
        return False

    # Eliminar por document_number
    response = api_request("DELETE", f"/budget/actual-cost/by-document/{bulk_doc_number}")
    if response is not None and response.status_code == 200:
        data = response.json()
        records_deleted = data.get("records_deleted", 0)
        if records_deleted == records_to_create:
            # Verificar que fueron eliminados (consultar por ID)
            all_gone = True
            for cost_id in created_ids:
                verify_resp = api_request("GET", f"/budget/actual-cost/{cost_id}")
                if verify_resp is not None and verify_resp.status_code == 200:
                    all_gone = False
                    break
            if all_gone:
                log_test(12, 17, "Delete by document_number", True, f"deleted {records_deleted} records")
                return True
            else:
                log_test(12, 17, "Delete by document_number", False, "some records still exist")
                return False
        else:
            log_test(12, 17, "Delete by document_number", False, f"expected {records_to_create} deleted, got {records_deleted}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(12, 17, "Delete by document_number", False, detail[:80])
        # Limpiar manualmente
        for cost_id in created_ids:
            api_request("DELETE", f"/budget/actual-cost/{cost_id}")
        return False


def test_13_upload_etl_costos_file():
    """
    Upload ETL de Costos.xlsx vía POST /budget/upload/actual-costs.
    Verifica que la respuesta incluye replaced=false (primera carga).
    """
    if not Path(COST_EXCEL_PATH).exists():
        log_test(13, 17, "Upload ETL Costos.xlsx", False, f"file not found: {COST_EXCEL_PATH}")
        return False

    # Calcular excel_total_cost desde el archivo
    try:
        df = pd.read_excel(COST_EXCEL_PATH, header=3, skipfooter=1)
        df_clean = df.dropna(subset=['Doc'])
        excel_total_cost = float((df_clean['Unidades'] * df_clean['Costo Unitario']).sum())
        expected_rows = len(df_clean)
    except Exception as e:
        log_test(13, 17, "Upload ETL Costos.xlsx", False, f"error reading Excel: {str(e)[:50]}")
        return False

    # Pre-cleanup: eliminar registros ETL existentes para garantizar replaced=false
    excel_filename = Path(COST_EXCEL_PATH).name
    try:
        response = api_request("GET", "/budget/actual-cost/?limit=10000")
        if response is not None and response.status_code == 200:
            existing = response.json()
            etl_docs = set(
                r["document_number"] for r in existing
                if r.get("source_file") == excel_filename
            )
            for doc_num in etl_docs:
                api_request("DELETE", f"/budget/actual-cost/by-document/{doc_num}")
    except Exception:
        pass

    with open(COST_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(COST_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"excel_total_cost": excel_total_cost}
        response = api_request("POST", "/budget/upload/actual-costs", files=files, data=data)

    if response is not None and response.status_code == 200:
        data = response.json()
        records_inserted = data.get("records_inserted", 0)
        total_amount = data.get("total_amount", 0)
        replaced = data.get("replaced", None)
        records_deleted = data.get("records_deleted", None)

        state.etl_inserted_count = records_inserted
        state.first_upload_count = records_inserted

        # Verificar campos de reemplazo
        if replaced is None or records_deleted is None:
            log_test(13, 17, "Upload ETL Costos.xlsx", False, "missing replaced/records_deleted fields")
            return False

        if records_inserted == expected_rows and replaced == False and records_deleted == 0:
            log_test(13, 17, "Upload ETL Costos.xlsx", True,
                    f"inserted={records_inserted}, replaced={replaced}, deleted={records_deleted}")
            return True
        else:
            log_test(13, 17, "Upload ETL Costos.xlsx", False,
                    f"expected={expected_rows}, got={records_inserted}, replaced={replaced}, deleted={records_deleted}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(13, 17, "Upload ETL Costos.xlsx", False, detail[:80])
        return False


def test_14_verify_etl_inserted_records():
    """Verificar que los registros insertados por ETL existen en la BD."""
    if state.etl_inserted_count == 0:
        log_test(14, 17, "Verify ETL inserted records", False, "no records inserted by ETL")
        return False

    # Obtener registros para extraer document_numbers
    response = api_request("GET", f"/budget/actual-cost/?limit={state.etl_inserted_count + 100}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if len(data) >= state.etl_inserted_count:
            # Extraer document_numbers únicos de los registros ETL (source_file = nombre del archivo)
            excel_filename = Path(COST_EXCEL_PATH).name
            etl_records = [r for r in data if r.get("source_file") == excel_filename]
            state.etl_document_numbers = list(set(r["document_number"] for r in etl_records))

            log_test(14, 17, "Verify ETL inserted records", True,
                    f"verified {len(data)} records, {len(state.etl_document_numbers)} unique documents")
            return True
        else:
            log_test(14, 17, "Verify ETL inserted records", False,
                    f"expected {state.etl_inserted_count}, got {len(data)}")
            return False
    else:
        log_test(14, 17, "Verify ETL inserted records", False,
                f"status {response.status_code if response is not None else 'error'}")
        return False


def test_15_upload_etl_reemplazo():
    """
    Subir el mismo archivo Excel una segunda vez para probar reemplazo automático.
    Verifica que replaced=true y records_deleted > 0.
    """
    if state.first_upload_count == 0:
        log_test(15, 17, "Upload ETL reemplazo", False, "no first upload to replace")
        return False

    # Calcular excel_total_cost desde el archivo
    try:
        df = pd.read_excel(COST_EXCEL_PATH, header=3, skipfooter=1)
        df_clean = df.dropna(subset=['Doc'])
        excel_total_cost = float((df_clean['Unidades'] * df_clean['Costo Unitario']).sum())
        expected_rows = len(df_clean)
    except Exception as e:
        log_test(15, 17, "Upload ETL reemplazo", False, f"error reading Excel: {str(e)[:50]}")
        return False

    with open(COST_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(COST_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"excel_total_cost": excel_total_cost}
        response = api_request("POST", "/budget/upload/actual-costs", files=files, data=data)

    if response is not None and response.status_code == 200:
        data = response.json()
        records_inserted = data.get("records_inserted", 0)
        replaced = data.get("replaced", None)
        records_deleted = data.get("records_deleted", None)

        state.second_upload_count = records_inserted

        # Verificar que hubo reemplazo
        if replaced == True and records_deleted > 0:
            log_test(15, 17, "Upload ETL reemplazo", True,
                    f"replaced={replaced}, deleted={records_deleted}, inserted={records_inserted}")
            return True
        else:
            log_test(15, 17, "Upload ETL reemplazo", False,
                    f"expected replaced=True, got replaced={replaced}, deleted={records_deleted}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(15, 17, "Upload ETL reemplazo", False, detail[:80])
        return False


def test_16_verify_reemplazo():
    """Verificar que después del reemplazo no hay duplicados."""
    if state.second_upload_count == 0:
        log_test(16, 17, "Verify reemplazo", False, "no second upload to verify")
        return False

    # Obtener todos los registros
    response = api_request("GET", f"/budget/actual-cost/?limit=10000")
    if response is not None and response.status_code == 200:
        data = response.json()
        excel_filename = Path(COST_EXCEL_PATH).name
        etl_records = [r for r in data if r.get("source_file") == excel_filename]

        # Verificar que el total es igual al second_upload_count (no el doble)
        if len(etl_records) == state.second_upload_count:
            log_test(16, 17, "Verify reemplazo", True,
                    f"no duplicates: {len(etl_records)} records (expected {state.second_upload_count})")
            return True
        else:
            log_test(16, 17, "Verify reemplazo", False,
                    f"expected {state.second_upload_count}, got {len(etl_records)} (possible duplicates)")
            return False
    else:
        log_test(16, 17, "Verify reemplazo", False,
                f"status {response.status_code if response is not None else 'error'}")
        return False


def test_17_cleanup_etl_records():
    """Limpiar registros ETL usando delete by document_number."""
    if not state.etl_document_numbers:
        log_test(17, 17, "Cleanup ETL records", True, "nothing to clean")
        return True

    deleted_total = 0
    for doc_number in state.etl_document_numbers:
        response = api_request("DELETE", f"/budget/actual-cost/by-document/{doc_number}")
        if response is not None and response.status_code == 200:
            data = response.json()
            deleted_total += data.get("records_deleted", 0)

    if deleted_total > 0:
        log_test(17, 17, "Cleanup ETL records", True,
                f"deleted {deleted_total} records across {len(state.etl_document_numbers)} documents")
        return True
    else:
        log_test(17, 17, "Cleanup ETL records", False, "no records deleted")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Actual Cost Module Smoke Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User: {USERNAME}")
    print(f"Excel file: {COST_EXCEL_PATH}")
    print()

    tests = [
        test_01_login,
        test_02_list_cost_centers,
        test_03_list_references,
        test_04_create_actual_cost,
        test_05_get_actual_cost,
        test_06_list_actual_costs,
        test_07_update_actual_cost,
        test_08_validate_invalid_cost_center,
        test_09_validate_negative_quantity,
        test_10_delete_actual_cost,
        test_11_cleanup_crud_records,
        test_12_delete_by_document_number,
        test_13_upload_etl_costos_file,
        test_14_verify_etl_inserted_records,
        test_15_upload_etl_reemplazo,
        test_16_verify_reemplazo,
        test_17_cleanup_etl_records,
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

    if state.created_actual_cost_ids:
        print(f"\nActual costs creados (para limpieza manual): {state.created_actual_cost_ids}")

    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
