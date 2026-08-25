"""
Budget Module Smoke Tests

Prueba los endpoints del módulo de presupuestos:
- LinePaymentRule CRUD
- Upload de presupuestos (income y expense)
- Verificación de datos creados

Uso:
    1. Copiar .env_test.example a .env_test
    2. Editar .env_test con tus credenciales y rutas
    3. python test_budget_smoke.py
"""

import sys
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
INCOME_EXCEL_PATH = config.get("INCOME_EXCEL_PATH", "").strip('"\'')
EXPENSE_EXCEL_PATH = config.get("EXPENSE_EXCEL_PATH", "").strip('"\'')

if not USERNAME or not PASSWORD:
    print("ERROR: USERNAME y PASSWORD son requeridos en .env_test")
    sys.exit(1)

if not INCOME_EXCEL_PATH or not EXPENSE_EXCEL_PATH:
    print("ERROR: INCOME_EXCEL_PATH y EXPENSE_EXCEL_PATH son requeridos en .env_test")
    sys.exit(1)

print(BASE_URL)
print(USERNAME)
print(PASSWORD)
print(INCOME_EXCEL_PATH)
print(EXPENSE_EXCEL_PATH)

# Datos para crear presupuesto de prueba
TEST_BUDGET_NAME = "Smoke Test Budget"
TEST_BUDGET_YEAR = 2025
TEST_BUDGET_PERIOD = "annual"

# ══════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════

class TestState:
    def __init__(self):
        self.token = None
        self.headers = {}
        self.test_cost_center_id = None
        self.test_collection_id = None
        self.test_line_id = None
        self.created_budget_ids = []
        self.created_rule_ids = []
        self.passed = 0
        self.failed = 0
        self.results = []

state = TestState()

# ══════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════

def log_test(num: int, total: int, name: str, success: bool, detail: str = ""):
    status = "✓" if success else "✗"
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
    except requests.exceptions.RequestException as e:
        return None


# ══════════════════════════════════════════════════════════════
# PRUEBAS
# ══════════════════════════════════════════════════════════════

def test_01_login():
    response = api_request("POST", "/login/", json={
        "username": USERNAME,
        "password": PASSWORD
    })
    if response and response.status_code == 200:
        data = response.json()
        state.token = data.get("access_token")
        state.headers = {"Authorization": f"Bearer {state.token}"}
        log_test(1, 15, "Login", True, "JWT obtenido")
        return True
    else:
        detail = response.text if response else "Connection error"
        log_test(1, 15, "Login", False, detail[:50])
        return False


def test_02_list_cost_centers():
    response = api_request("GET", "/budget/cost-center/?limit=5")
    if response and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_cost_center_id = data[0]["id_cost_center"]
            log_test(2, 15, "List cost centers", True, f"found {len(data)}")
            return True
        else:
            log_test(2, 15, "List cost centers", False, "no data found")
            return False
    else:
        log_test(2, 15, "List cost centers", False, f"status {response.status_code if response else 'error'}")
        return False


def test_03_list_collections():
    response = api_request("GET", "/collection/?limit=5")
    if response and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_collection_id = data[0]["id_collection"]
            log_test(3, 15, "List collections", True, f"found {len(data)}")
            return True
        else:
            log_test(3, 15, "List collections", False, "no data found")
            return False
    else:
        log_test(3, 15, "List collections", False, f"status {response.status_code if response else 'error'}")
        return False


def test_04_list_lines():
    response = api_request("GET", "/line/?limit=5")
    if response and response.status_code == 200:
        data = response.json()
        if data and len(data) > 0:
            state.test_line_id = data[0]["id_line"]
            log_test(4, 15, "List lines", True, f"found {len(data)}")
            return True
        else:
            log_test(4, 15, "List lines", False, "no data found")
            return False
    else:
        log_test(4, 15, "List lines", False, f"status {response.status_code if response else 'error'}")
        return False


def test_05_create_payment_rule():
    if not state.test_line_id:
        log_test(5, 15, "Create payment rule", False, "no line_id available")
        return False
    
    response = api_request("POST", "/line-payment-rule/", json={
        "id_line": state.test_line_id,
        "payment_pct": 0.5,
        "payment_days": -15
    })
    if response and response.status_code in (200, 201):
        data = response.json()
        rule_id = data.get("id_line_payment_rule")
        state.created_rule_ids.append(rule_id)
        log_test(5, 15, "Create payment rule", True, f"id={rule_id}")
        return True
    else:
        detail = response.text if response else "error"
        log_test(5, 15, "Create payment rule", False, detail[:50])
        return False


def test_06_get_payment_rule():
    if not state.created_rule_ids:
        log_test(6, 15, "Get payment rule", False, "no rule created")
        return False
    
    rule_id = state.created_rule_ids[0]
    response = api_request("GET", f"/line-payment-rule/{rule_id}")
    if response and response.status_code == 200:
        data = response.json()
        if data.get("id_line_payment_rule") == rule_id:
            log_test(6, 15, "Get payment rule", True, f"id={rule_id}")
            return True
        else:
            log_test(6, 15, "Get payment rule", False, "ID mismatch")
            return False
    else:
        log_test(6, 15, "Get payment rule", False, f"status {response.status_code if response else 'error'}")
        return False


def test_07_update_payment_rule():
    if not state.created_rule_ids:
        log_test(7, 15, "Update payment rule", False, "no rule created")
        return False
    
    rule_id = state.created_rule_ids[0]
    response = api_request("PUT", f"/line-payment-rule/{rule_id}", json={
        "id_line": state.test_line_id,
        "payment_pct": 0.75,
        "payment_days": -10
    })
    if response and response.status_code == 200:
        data = response.json()
        if data.get("payment_pct") == 0.75:
            log_test(7, 15, "Update payment rule", True, "pct updated to 0.75")
            return True
        else:
            log_test(7, 15, "Update payment rule", False, "update not applied")
            return False
    else:
        log_test(7, 15, "Update payment rule", False, f"status {response.status_code if response else 'error'}")
        return False


def test_08_list_rules_by_line():
    if not state.test_line_id:
        log_test(8, 15, "List rules by line", False, "no line_id")
        return False
    
    response = api_request("GET", f"/line-payment-rule/by-line/{state.test_line_id}")
    if response and response.status_code == 200:
        data = response.json()
        if len(data) > 0:
            log_test(8, 15, "List rules by line", True, f"found {len(data)}")
            return True
        else:
            log_test(8, 15, "List rules by line", False, "no rules found")
            return False
    else:
        log_test(8, 15, "List rules by line", False, f"status {response.status_code if response else 'error'}")
        return False


def test_09_delete_payment_rule():
    if not state.created_rule_ids:
        log_test(9, 15, "Delete payment rule", False, "no rule created")
        return False
    
    rule_id = state.created_rule_ids[0]
    response = api_request("DELETE", f"/line-payment-rule/{rule_id}")
    if response and response.status_code == 200:
        state.created_rule_ids.remove(rule_id)
        log_test(9, 15, "Delete payment rule", True, f"id={rule_id} deleted")
        return True
    else:
        log_test(9, 15, "Delete payment rule", False, f"status {response.status_code if response else 'error'}")
        return False


def test_10_upload_income():
    if not Path(INCOME_EXCEL_PATH).exists():
        log_test(10, 15, "Upload income budget", False, f"file not found: {INCOME_EXCEL_PATH}")
        return False
    
    with open(INCOME_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(INCOME_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {
            "budget_name": f"{TEST_BUDGET_NAME} - Income",
            "budget_year": TEST_BUDGET_YEAR,
            "budget_period": TEST_BUDGET_PERIOD,
        }
        response = api_request("POST", "/budget/upload/budget-plan-income", files=files, data=data)
    
    if response and response.status_code == 200:
        result = response.json()
        budget_id = result.get("id_budget")
        lines_count = result.get("budget_lines_count", 0)
        state.created_budget_ids.append(budget_id)
        log_test(10, 15, "Upload income budget", True, f"id={budget_id}, lines={lines_count}")
        return True
    else:
        detail = response.text if response else "error"
        log_test(10, 15, "Upload income budget", False, detail[:80])
        return False


def test_11_verify_budget_income():
    if not state.created_budget_ids:
        log_test(11, 15, "Verify income budget", False, "no budget created")
        return False
    
    budget_id = state.created_budget_ids[-1]
    response = api_request("GET", f"/budget/{budget_id}")
    if response and response.status_code == 200:
        data = response.json()
        if data.get("status") == "draft":
            log_test(11, 15, "Verify income budget", True, "status=draft")
            return True
        else:
            log_test(11, 15, "Verify income budget", False, f"status={data.get('status')}")
            return False
    else:
        log_test(11, 15, "Verify income budget", False, f"status {response.status_code if response else 'error'}")
        return False


def test_12_verify_budget_lines_income():
    if not state.created_budget_ids:
        log_test(12, 15, "Verify budget lines income", False, "no budget created")
        return False
    
    budget_id = state.created_budget_ids[-1]
    response = api_request("GET", f"/budget/line/by-budget/{budget_id}")
    if response and response.status_code == 200:
        data = response.json()
        if len(data) > 0:
            log_test(12, 15, "Verify budget lines income", True, f"found {len(data)} lines")
            return True
        else:
            log_test(12, 15, "Verify budget lines income", False, "no lines found")
            return False
    else:
        log_test(12, 15, "Verify budget lines income", False, f"status {response.status_code if response else 'error'}")
        return False


def test_13_upload_expense():
    if not Path(EXPENSE_EXCEL_PATH).exists():
        log_test(13, 15, "Upload expense budget", False, f"file not found: {EXPENSE_EXCEL_PATH}")
        return False
    
    with open(EXPENSE_EXCEL_PATH, "rb") as f:
        files = {"file": (Path(EXPENSE_EXCEL_PATH).name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {
            "budget_name": f"{TEST_BUDGET_NAME} - Expense",
            "budget_year": TEST_BUDGET_YEAR,
            "budget_period": TEST_BUDGET_PERIOD,
        }
        response = api_request("POST", "/budget/upload/budget-plan-expense", files=files, data=data)
    
    if response and response.status_code == 200:
        result = response.json()
        budget_id = result.get("id_budget")
        lines_count = result.get("budget_lines_count", 0)
        state.created_budget_ids.append(budget_id)
        log_test(13, 15, "Upload expense budget", True, f"id={budget_id}, lines={lines_count}")
        return True
    else:
        detail = response.text if response else "error"
        log_test(13, 15, "Upload expense budget", False, detail[:80])
        return False


def test_14_verify_budget_expense():
    if len(state.created_budget_ids) < 2:
        log_test(14, 15, "Verify expense budget", False, "no expense budget created")
        return False
    
    budget_id = state.created_budget_ids[-1]
    response = api_request("GET", f"/budget/{budget_id}")
    if response and response.status_code == 200:
        data = response.json()
        if data.get("status") == "draft":
            log_test(14, 15, "Verify expense budget", True, "status=draft")
            return True
        else:
            log_test(14, 15, "Verify expense budget", False, f"status={data.get('status')}")
            return False
    else:
        log_test(14, 15, "Verify expense budget", False, f"status {response.status_code if response else 'error'}")
        return False


def test_15_verify_budget_lines_expense():
    if len(state.created_budget_ids) < 2:
        log_test(15, 15, "Verify budget lines expense", False, "no expense budget created")
        return False
    
    budget_id = state.created_budget_ids[-1]
    response = api_request("GET", f"/budget/line/by-budget/{budget_id}")
    if response and response.status_code == 200:
        data = response.json()
        if len(data) > 0:
            log_test(15, 15, "Verify budget lines expense", True, f"found {len(data)} lines")
            return True
        else:
            log_test(15, 15, "Verify budget lines expense", False, "no lines found")
            return False
    else:
        log_test(15, 15, "Verify budget lines expense", False, f"status {response.status_code if response else 'error'}")
        return False


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Budget Module Smoke Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User: {USERNAME}")
    print()
    
    tests = [
        test_01_login,
        test_02_list_cost_centers,
        test_03_list_collections,
        test_04_list_lines,
        test_05_create_payment_rule,
        test_06_get_payment_rule,
        test_07_update_payment_rule,
        test_08_list_rules_by_line,
        test_09_delete_payment_rule,
        test_10_upload_income,
        test_11_verify_budget_income,
        test_12_verify_budget_lines_income,
        test_13_upload_expense,
        test_14_verify_budget_expense,
        test_15_verify_budget_lines_expense,
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
    
    if state.created_budget_ids:
        print(f"\nBudgets creados (para inspección): {state.created_budget_ids}")
    
    return 0 if state.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
