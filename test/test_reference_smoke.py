"""
Reference Module Smoke Tests

Prueba los endpoints del módulo de referencias:
- Reference CRUD individual
- Upload masivo desde Excel
- Eliminación masiva desde Excel
- Descarga de plantillas
- Validaciones de integridad

Uso:
    1. Copiar .env_test.example a .env_test
    2. Editar .env_test con tus credenciales
    3. python test_reference_smoke.py
"""

import sys
import time
import requests
from pathlib import Path
from dotenv import dotenv_values

# ══════════════════════════════════════════════════════════════
# CARGAR CONFIGURACIÓN DESDE .env_test
# ══════════════════════════════════════════════════════════════

TEST_DIR = Path(__file__).parent
ENV_FILE = TEST_DIR / ".env_test"

if not ENV_FILE.exists():
    print(f"ERROR: No se encontró {ENV_FILE}")
    print(f"Copia .env_test.example a .env_test y configura tus credenciales")
    sys.exit(1)

config = dotenv_values(ENV_FILE)

BASE_URL = config.get("BASE_URL", "http://127.0.0.1:8003").strip('"\'')
USERNAME = config.get("USERNAME", "").strip('"\'')
PASSWORD = config.get("PASSWORD", "").strip('"\'')
UPLOAD_EXCEL_PATH = config.get("UPLOAD_EXCEL_PATH", "").strip('"\'')
DELETE_EXCEL_PATH = config.get("DELETE_EXCEL_PATH", "").strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

if not UPLOAD_EXCEL_PATH or not DELETE_EXCEL_PATH:
    print("ERROR: UPLOAD_EXCEL_PATH y DELETE_EXCEL_PATH son requeridos en .env_test")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.test_brand_id = None
        self.test_collection_id = None
        self.test_reference_id = None
        self.created_reference_ids = []
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
    if detail and not success:
        msg += f" ({detail})"
    elif detail:
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


def test_02_list_brands():
    response = api_request("GET", "/brand/?limit=5")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_brand_id = data[0]["id_brand"]
            log_test(2, 16, "List brands", True, f"found {len(data)}, id={state.test_brand_id}")
            return True
        else:
            log_test(2, 16, "List brands", False, "no brands found")
            return False
    else:
        log_test(2, 16, "List brands", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_03_list_collections():
    response = api_request("GET", "/collection/?limit=5")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_collection_id = data[0]["id_collection"]
            log_test(3, 16, "List collections", True, f"found {len(data)}, id={state.test_collection_id}")
            return True
        else:
            log_test(3, 16, "List collections", False, "no collections found (optional)")
            state.test_collection_id = None
            return True
    else:
        log_test(3, 16, "List collections", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_04_create_reference():
    if not state.test_brand_id:
        log_test(4, 16, "Create reference", False, "no brand_id available")
        return False
    
    reference_data = {
        "reference": "TEST-REF-001",
        "id_brand": state.test_brand_id,
        "description": "Referencia de prueba para smoke test",
        "gender": 0,
        "value_base": 100.50,
    }
    
    if state.test_collection_id:
        reference_data["id_collection"] = state.test_collection_id
    
    response = api_request("POST", "/reference/", json=reference_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        ref_id = data.get("id_reference")
        state.test_reference_id = ref_id
        state.created_reference_ids.append(ref_id)
        log_test(4, 16, "Create reference", True, f"id={ref_id}")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(4, 16, "Create reference", False, detail[:80])
        return False


def test_05_get_reference():
    if not state.test_reference_id:
        log_test(5, 16, "Get reference", False, "no reference created")
        return False
    
    response = api_request("GET", f"/reference/{state.test_reference_id}")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("id_reference") == state.test_reference_id:
            log_test(5, 16, "Get reference", True, f"id={state.test_reference_id}")
            return True
        else:
            log_test(5, 16, "Get reference", False, "ID mismatch")
            return False
    else:
        log_test(5, 16, "Get reference", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_06_list_references():
    response = api_request("GET", "/reference/?limit=10")
    if response is not None and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            log_test(6, 16, "List references", True, f"found {len(data)}")
            return True
        else:
            log_test(6, 16, "List references", False, "no references found")
            return False
    else:
        log_test(6, 16, "List references", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_07_update_reference():
    if not state.test_reference_id:
        log_test(7, 16, "Update reference", False, "no reference created")
        return False
    
    update_data = {
        "reference": "TEST-REF-001-UPDATED",
        "id_brand": state.test_brand_id,
        "description": "Referencia actualizada",
        "gender": 1,
        "value_base": 200.75,
    }
    
    if state.test_collection_id:
        update_data["id_collection"] = state.test_collection_id
    
    response = api_request("PUT", f"/reference/{state.test_reference_id}", json=update_data)
    if response is not None and response.status_code == 200:
        data = response.json()
        if data.get("value_base") == 200.75 and data.get("gender") == 1:
            log_test(7, 16, "Update reference", True, "value_base and gender updated")
            return True
        else:
            log_test(7, 16, "Update reference", False, "update not applied correctly")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(7, 16, "Update reference", False, detail[:80])
        return False


def test_08_create_reference_for_duplicate_test():
    if not state.test_brand_id:
        log_test(8, 16, "Create duplicate reference test", False, "no brand_id")
        return False
    
    reference_data = {
        "reference": "TEST-REF-DUPLICATE",
        "id_brand": state.test_brand_id,
        "description": "Primera creación",
        "gender": 2,
        "value_base": 50.00,
    }
    
    response = api_request("POST", "/reference/", json=reference_data)
    if response is not None and response.status_code in (200, 201):
        data = response.json()
        ref_id = data.get("id_reference")
        state.created_reference_ids.append(ref_id)
        
        time.sleep(0.5)
        
        response2 = api_request("POST", "/reference/", json=reference_data)
        if response2 is not None and response2.status_code in (400, 409):
            log_test(8, 16, "Create duplicate reference test", True, "duplicate rejected")
            return True
        else:
            detail = f"status={response2.status_code if response2 is not None else 'None'}"
            log_test(8, 16, "Create duplicate reference test", False, detail)
            return False
    else:
        detail = f"first POST status={response.status_code if response is not None else 'None'}"
        log_test(8, 16, "Create duplicate reference test", False, detail)
        return False


def test_09_download_upload_template():
    response = api_request("GET", "/reference/template")
    if response is not None and response.status_code == 200:
        content_type = response.headers.get("content-type", "")
        if "spreadsheet" in content_type or "excel" in content_type or "octet-stream" in content_type:
            log_test(9, 16, "Download upload template", True, "Excel file received")
            return True
        else:
            log_test(9, 16, "Download upload template", False, f"unexpected content-type: {content_type}")
            return False
    else:
        log_test(9, 16, "Download upload template", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_10_download_delete_template():
    response = api_request("GET", "/reference/template-delete")
    if response is not None and response.status_code == 200:
        content_type = response.headers.get("content-type", "")
        if "spreadsheet" in content_type or "excel" in content_type or "octet-stream" in content_type:
            log_test(10, 16, "Download delete template", True, "Excel file received")
            return True
        else:
            log_test(10, 16, "Download delete template", False, f"unexpected content-type: {content_type}")
            return False
    else:
        log_test(10, 16, "Download delete template", False, f"status {response.status_code if response is not None else 'error'}")
        return False


def test_11_delete_reference():
    if not state.created_reference_ids:
        log_test(11, 16, "Delete reference", False, "no reference to delete")
        return False
    
    ref_id = state.created_reference_ids[-1]
    response = api_request("DELETE", f"/reference/{ref_id}")
    if response is not None and response.status_code == 200:
        state.created_reference_ids.remove(ref_id)
        log_test(11, 16, "Delete reference", True, f"id={ref_id} deleted")
        return True
    else:
        detail = response.text if response is not None else "error"
        log_test(11, 16, "Delete reference", False, detail[:80])
        return False


def test_12_cleanup_references():
    if not state.created_reference_ids:
        log_test(12, 16, "Cleanup references", True, "nothing to clean")
        return True
    
    deleted_count = 0
    for ref_id in state.created_reference_ids[:]:
        response = api_request("DELETE", f"/reference/{ref_id}")
        if response is not None and response.status_code == 200:
            state.created_reference_ids.remove(ref_id)
            deleted_count += 1
    
    if deleted_count > 0 or len(state.created_reference_ids) == 0:
        log_test(12, 16, "Cleanup references", True, f"deleted {deleted_count}")
        return True
    else:
        log_test(12, 16, "Cleanup references", False, "some references not deleted")
        return False


def test_13_validate_brand_existence():
    response = api_request("POST", "/reference/", json={
        "reference": "TEST-INVALID-BRAND",
        "id_brand": 999999,
        "description": "Test with invalid brand",
        "gender": 0,
        "value_base": 100.00,
    })
    
    if response is not None and response.status_code in (400, 404, 422):
        log_test(13, 16, "Validate brand existence", True, "invalid brand rejected")
        return True
    else:
        log_test(13, 16, "Validate brand existence", False, "invalid brand not rejected")
        return False


def test_14_validate_gender_enum():
    response = api_request("POST", "/reference/", json={
        "reference": "TEST-INVALID-GENDER",
        "id_brand": state.test_brand_id if state.test_brand_id else 1,
        "description": "Test with invalid gender",
        "gender": 99,
        "value_base": 100.00,
    })
    
    if response is not None and response.status_code in (400, 422):
        log_test(14, 16, "Validate gender enum", True, "invalid gender rejected")
        return True
    else:
        log_test(14, 16, "Validate gender enum", False, "invalid gender not rejected")
        return False


def test_15_bulk_upload_references():
    if not Path(UPLOAD_EXCEL_PATH).exists():
        log_test(15, 16, "Bulk upload references", False, f"file not found: {UPLOAD_EXCEL_PATH}")
        return False
    
    with open(UPLOAD_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(UPLOAD_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = api_request("POST", "/reference/upload", files=files)
    
    if response is not None and response.status_code == 200:
        data = response.json()
        total = data.get("total_filas", 0)
        insertadas = data.get("insertadas", 0)
        actualizadas = data.get("actualizadas", 0)
        errores = data.get("errores", [])
        
        if len(errores) == 0:
            log_test(15, 16, "Bulk upload references", True, f"total={total}, insertadas={insertadas}, actualizadas={actualizadas}")
            return True
        else:
            log_test(15, 16, "Bulk upload references", False, f"errores={errores}")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(15, 16, "Bulk upload references", False, detail[:80])
        return False


def test_16_bulk_delete_references():
    if not Path(DELETE_EXCEL_PATH).exists():
        log_test(16, 16, "Bulk delete references", False, f"file not found: {DELETE_EXCEL_PATH}")
        return False
    
    with open(DELETE_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(DELETE_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = api_request("POST", "/reference/delete-bulk", files=files)
    
    if response is not None and response.status_code == 200:
        data = response.json()
        total = data.get("total_eliminadas", 0)
        eliminadas = data.get("referencias_eliminadas", [])
        
        if total > 0:
            log_test(16, 16, "Bulk delete references", True, f"eliminadas={total}")
            return True
        else:
            log_test(16, 16, "Bulk delete references", False, "no references deleted")
            return False
    else:
        detail = response.text if response is not None else "error"
        log_test(16, 16, "Bulk delete references", False, detail[:80])
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Reference Module Smoke Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User: {USERNAME}")
    print()
    
    tests = [
        test_01_login,
        test_02_list_brands,
        test_03_list_collections,
        test_04_create_reference,
        test_05_get_reference,
        test_06_list_references,
        test_07_update_reference,
        test_08_create_reference_for_duplicate_test,
        test_09_download_upload_template,
        test_10_download_delete_template,
        test_11_delete_reference,
        test_12_cleanup_references,
        test_13_validate_brand_existence,
        test_14_validate_gender_enum,
        test_15_bulk_upload_references,
        test_16_bulk_delete_references,
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
    
    if state.created_reference_ids:
        print(f"\nReferencias creadas (para limpieza manual): {state.created_reference_ids}")
    
    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
