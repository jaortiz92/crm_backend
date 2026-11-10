"""
Labor Cost Engine — Nómina Smoke (backend.02_27, AC-1/AC-5/AC-6/AC-7/AC-8)

Self-contained smoke: SIN Docker, SIN BD real, SIN API. SQLite in-memory
(``create_all`` con TODOS los modelos importados vía ``app.models`` —
registra las FKs: collaborators -> cost_centers/collections, accruals ->
cost_components, etc.). El motor se ejercita directamente
``LaborCostEngine.compute_month(collab, month, persist=False)`` (ruta
pura del breakdown; persist=True también funcionaría en SQLite: los
helpers del CRUD usan ``db.query`` ORM, sin SQL crudo de Postgres).

Semilla de vigencia 2026 (backend.02_21 §4.3 valores de prueba):
smlv=1500000, salud_patronal_pct=0.085, pension_pct=0.12, caja_pct=0.04,
caja_tope_smlv=25, sena_pct=0.03, icbf_pct=0.03, prima_tasa=0.0833,
cesantias_tasa=0.0833, intereses=0.12, etc. Los keys EXACTOS salen de
_DEPENDENT_KEYS/_SERVICE_KEYS del motor; los keys mode-only
(parafiscales_tope_exoneracion_smlv, liquidar_*) se siembran solo en los
casos que los usan (R-05: el motor no adivina).

Cobertura:
  - AC-1  pays_pension=False => mes completo SIN C_PENSION (SAL/SALUD/
          ARL/CAJA/aux + provisiones intactas); True => lo contiene.
  - AC-5  exonerated_lt100 + tope=10 SMLV: IBC < tope => sin SENA/ICBF,
          con CAJA; IBC >= tope => con SENA+ICBF+CAJA.
  - AC-6  custom + liquidar_sena="0"/liquidar_icbf="1"/liquidar_caja="1"
          => sin C_SENA, con C_ICBF y C_CAJA.
  - AC-7  custom SIN liquidar_* => MissingLaborParametersError (R-05).
  - AC-8  plantilla Excel: columna "Cotiza pension" (SÍ/SI/TRUE/1/S,
          NO/FALSE/0/N, vacío => None, inválido => 400 R-06; plantilla
          sin la columna importa OK). El procesador es invocable de
          verdad: se fabrica el .xlsx en memoria con openpyxl
          (headers fila 8, datos fila 9 — layout D-S11-1).

Uso (desde crm_backend/):
    .\\venv_backend\\Scripts\\python.exe test\\test_labor_cost_engine_nomina_smoke.py
"""

import os
import sys
import traceback
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

# Consolas de Windows (cp1252) no codifican los caracteres graficos
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ────────────────────────────────────────────────────────────────────
# app.settings (BaseSettings) exige ENV/POSTGRES_*/JWT en el import de
# app.db. No toca BD real: los valores son dummy y el engine de
# database.py nunca se conecta (lazy). SQLite vive SOLO en el test.
# ────────────────────────────────────────────────────────────────────
_DUMMY = {
    "ENV": "development",
    "POSTGRES_USER": "smoke",
    "POSTGRES_PASSWORD": "smoke",
    "POSTGRES_DB": "smoke",
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433",
    "SECRET_KEY": "smoke-key",
    "ALGORITHM": "HS256",
    "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "BACKEND_CORS_ORIGINS": "http://localhost",
    "USERNAME": "smoke",
    "CLIENT_ID": "smoke",
    "CLIENT_SECRET": "smoke",
    "TENANT_ID": "smoke",
    "FRONTEND_URL": "http://localhost",
}
for _k, _v in _DUMMY.items():
    os.environ.setdefault(_k, _v)

import openpyxl  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402
import app.models  # noqa: E402,F401  registra TODAS las tablas (FKs)
import app.models.budget  # noqa: E402,F401
import app.models.budget.collaborator  # noqa: E402,F401
import app.api  # noqa: E402,F401  resuelve primero el ciclo de imports
# auth <-> api.utils (mismo orden de arranque que app.main) para que
# `import app.crud` no entre por auth parcialmente inicializado.
import app.crud as crud  # noqa: E402
from app.models.budget import (  # noqa: E402
    Collaborator, CollaboratorSalaryPlan, CostComponent,
    CostCenter, LaborArlRate, LaborCostParameter,
)
from app.services.laborCostEngine import (  # noqa: E402
    LaborCostEngine, MissingLaborParametersError,
    _REQUIRED_CATALOG,
)
from app.utils.templates import BudgetTemplates  # noqa: E402

VIGENCIA = 2026
MONTH = date(VIGENCIA, 6, 1)

_BASE_PARAMS = {
    "smlv": "1500000",
    "aux_transporte_valor": "200000",
    "aux_transporte_tope_smlv": "2",
    "salud_patronal_pct": "0.085",
    "pension_pct": "0.12",
    "caja_pct": "0.04",
    "caja_tope_smlv": "25",
    "sena_pct": "0.03",
    "icbf_pct": "0.03",
    "aplicacion_parafiscales": "all",
    "prima_tasa": "0.0833",
    "prima_tope_smlv_base": "30",
    "cesantias_tasa": "0.0833",
    "intereses_cesantias_anual": "0.12",
    "integral_ibc_factor": "0.7",
    "integral_tope_smlv": "25",
    "dia_pago_salario": "last_business_day",
    "fecha_prima_1": "06-30",
    "fecha_prima_2": "12-20",
    "fecha_intereses": "01-31",
    "fecha_cesantias": "02-14",
    "arl_default_class": "I",
}

_COMPONENT_LAYERS = {
    "SAL": "CAJA", "C1S": "CAJA", "TRA": "CAJA",
    "SALUD": "CAJA", "PENSION": "CAJA", "ARL": "CAJA",
    "CAJA": "CAJA", "SENA": "CAJA", "ICBF": "CAJA",
    "PRIMA": "PROVISION", "CESANTIAS": "PROVISION",
    "INTERESES": "PROVISION", "LIQ": "PROVISION",
}

_RESULTS = []


def _seed_catalog(db):
    """Catálogo de componentes (fase 3 §4.8) + tarifa ARL clase I."""
    for code in _REQUIRED_CATALOG:
        db.add(CostComponent(
            code=code, name=f"Componente {code}",
            layer=_COMPONENT_LAYERS.get(code, "CAJA"),
            is_legal=True, is_active=True,
        ))
    db.add(LaborArlRate(
        vigencia=VIGENCIA, risk_class="I", rate=Decimal("0.00522"),
    ))
    db.flush()


def _seed_params(db, extra=None):
    """Vigencia 2026: _BASE_PARAMS + los mode-only del caso."""
    values = dict(_BASE_PARAMS)
    values.update(extra or {})
    for key, value in values.items():
        db.add(LaborCostParameter(
            vigencia=VIGENCIA, key=key, value=value,
        ))
    db.flush()


def _set_params(db, extra=None, remove=()):
    """Rewrite the vigencia params (fresh rows; unique per vigencia+key
    so the old ones are deleted first)."""
    db.query(LaborCostParameter).filter(
        LaborCostParameter.vigencia == VIGENCIA,
    ).delete(synchronize_session=False)
    values = dict(_BASE_PARAMS)
    values.update(extra or {})
    for key in remove:
        values.pop(key, None)
    for key, value in values.items():
        db.add(LaborCostParameter(
            vigencia=VIGENCIA, key=key, value=value,
        ))
    db.flush()


def _make_collab(db, doc_value, salary, pays_pension=True,
                 contract_type="open_ended"):
    cc = db.query(CostCenter).filter(
        CostCenter.cost_center_code == "CC01",
    ).first()
    if cc is None:
        cc = CostCenter(cost_center_code="CC01", cost_center_name="CECO 1")
        db.add(cc)
        db.flush()
    collab = Collaborator(
        doc_type="CC", doc_value=doc_value, full_name=f"Colab {doc_value}",
        id_cost_center=cc.id_cost_center, contract_type=contract_type,
        status="active", hire_date=date(2026, 1, 1),
        pays_pension=pays_pension,
    )
    db.add(collab)
    db.flush()
    db.add(CollaboratorSalaryPlan(
        id_collaborator=collab.id_collaborator,
        salary=Decimal(salary),
        allowance_salary=Decimal("0"),
        allowance_non_salary=Decimal("0"),
        is_integral=False,
        valid_from=date(2026, 1, 1),
    ))
    db.flush()
    return collab


def _codes(seats):
    return {s.component_code for s in seats}


def _build_payroll_xlsx(pension_values):
    """Minimal nómina workbook: headers row 8 (skiprows=7), data row 9."""
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "Documento", "Tipo Documento", "Nombres y Apellidos",
        "Tipo de Contrato", "Salario Básico Mensual", "Centro de Costo",
    ]
    if pension_values is not None:
        headers.append("Cotiza pension")
    for col, head in enumerate(headers, start=1):
        ws.cell(row=8, column=col, value=head)
    rows = [
        ("10102030", "CC", "Ana Perez", "Término indefinido",
         2000000, "CC01"),
        ("10203040", "CC", "Bruno Diaz", "Término indefinido",
         2000000, "CC01"),
    ]
    if pension_values is not None:
        rows = [row + (val,) for row, val in zip(rows, pension_values)]
    for r_idx, row in enumerate(rows, start=9):
        for c_idx, value in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=value)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════
# Cases
# ════════════════════════════════════════════════════════════════════

def case_ac1_pays_pension(db):
    """AC-1: pays_pension=False => SIN C_PENSION (resto intacto)."""
    _seed_catalog(db)
    _seed_params(db)
    no_pension = _make_collab(db, "700100", "2000000", pays_pension=False)
    with_pension = _make_collab(db, "700200", "2000000", pays_pension=True)

    engine = LaborCostEngine(db)
    seats = engine.compute_month(no_pension, MONTH, persist=False)
    codes = _codes(seats)
    assert "PENSION" not in codes, f"AC-1: PENSION presente {codes}"
    for expected in ("SAL", "SALUD", "ARL", "CAJA"):
        assert expected in codes, f"AC-1: falta {expected} en {codes}"
    for prov in ("PRIMA", "CESANTIAS", "INTERESES"):
        assert prov in codes, f"AC-1: falta provision {prov} en {codes}"

    seats_true = LaborCostEngine(db).compute_month(
        with_pension, MONTH, persist=False,
    )
    assert "PENSION" in _codes(seats_true), "AC-1: True debe emitir PENSION"

    # breakdown (persist=False) debe ser identico en el flag False:
    # sin PENSION tambien en la vista derivada.
    breakdown = LaborCostEngine(db).breakdown(no_pension, MONTH)
    assert all(
        c["code"] != "PENSION" for c in breakdown["components"]
    ), "AC-1: breakdown expuso PENSION"


def case_ac5_exonerated(db):
    """AC-5: exonerated_lt100 (tope 10 SMLV) POR colaborador."""
    _set_params(db, extra={
        "aplicacion_parafiscales": "exonerated_lt100",
        "parafiscales_tope_exoneracion_smlv": "10",
    })
    low = _make_collab(db, "700300", "2000000")     # IBC 2M < 15M
    high = _make_collab(db, "700400", "16000000")   # IBC 16M >= 15M

    seats_low = LaborCostEngine(db).compute_month(low, MONTH, persist=False)
    codes_low = _codes(seats_low)
    assert "SENA" not in codes_low, f"AC-5 low: SENA presente {codes_low}"
    assert "ICBF" not in codes_low, f"AC-5 low: ICBF presente {codes_low}"
    assert "CAJA" in codes_low, f"AC-5 low: falta CAJA {codes_low}"

    seats_high = LaborCostEngine(db).compute_month(
        high, MONTH, persist=False,
    )
    codes_high = _codes(seats_high)
    for comp in ("SENA", "ICBF", "CAJA"):
        assert comp in codes_high, f"AC-5 high: falta {comp} {codes_high}"


def case_ac6_custom(db):
    """AC-6: custom con liquidar_sena='0' / icbf='1' / caja='1'."""
    _set_params(db, extra={
        "aplicacion_parafiscales": "custom",
        "liquidar_caja": "1",
        "liquidar_sena": "0",
        "liquidar_icbf": "1",
    })
    collab = _make_collab(db, "700500", "2000000")
    codes = _codes(
        LaborCostEngine(db).compute_month(collab, MONTH, persist=False)
    )
    assert "SENA" not in codes, f"AC-6: SENA presente {codes}"
    assert "ICBF" in codes, f"AC-6: falta ICBF {codes}"
    assert "CAJA" in codes, f"AC-6: falta CAJA {codes}"


def case_ac7_custom_missing(db):
    """AC-7: custom SIN liquidar_* => MissingLaborParametersError."""
    _set_params(db, extra={"aplicacion_parafiscales": "custom"}, remove=(
        "liquidar_caja", "liquidar_sena", "liquidar_icbf",
    ))
    collab = _make_collab(db, "700600", "2000000")
    try:
        LaborCostEngine(db).compute_month(collab, MONTH, persist=False)
    except MissingLaborParametersError as exc:
        assert exc.vigencia == VIGENCIA
        assert exc.key in ("liquidar_caja", "liquidar_sena",
                           "liquidar_icbf"), f"AC-7: key inesperada {exc.key}"
        return
    raise AssertionError(
        "AC-7: custom sin liquidar_* no lanzo MissingLaborParametersError"
    )


def case_ac8_template(db):
    """AC-8: parseo real de la columna 'Cotiza pension' con openpyxl."""
    # a) valores validos + vacio
    etl = BudgetTemplates(_build_payroll_xlsx(["SÍ", "no"]))
    etl.process_budget_plan_collaborators()
    recs = etl.dataframe_to_records()
    assert recs[0]["pays_pension"] is True, f"AC-8: SÍ => {recs[0]}"
    assert recs[1]["pays_pension"] is False, f"AC-8: no => {recs[1]}"

    # variantes case-insensitive / sin tilde / booleanos y numeros
    etl = BudgetTemplates(_build_payroll_xlsx(["SI", "TRUE"]))
    etl.process_budget_plan_collaborators()
    recs = etl.dataframe_to_records()
    assert recs[0]["pays_pension"] is True and recs[1]["pays_pension"] is True

    etl = BudgetTemplates(_build_payroll_xlsx([1, 0]))  # Excel numerico
    etl.process_budget_plan_collaborators()
    recs = etl.dataframe_to_records()
    assert recs[0]["pays_pension"] is True and recs[1]["pays_pension"] is False

    # b) vacio => None (alta default True / re-import keep, §7.2)
    etl = BudgetTemplates(_build_payroll_xlsx([None, ""]))
    etl.process_budget_plan_collaborators()
    recs = etl.dataframe_to_records()
    assert recs[0]["pays_pension"] is None and recs[1]["pays_pension"] is None

    # c) invalido no vacio => 400 estructurado (all-or-nothing R-06)
    try:
        etl = BudgetTemplates(_build_payroll_xlsx(["SÍ", "CASI"]))
        etl.process_budget_plan_collaborators()
    except Exception as exc:
        from fastapi import HTTPException
        assert isinstance(exc, HTTPException), f"AC-8: {type(exc)} {exc}"
        assert exc.status_code == 400, f"AC-8: status {exc.status_code}"
        detail = exc.detail
        assert "CASI" in str(detail), f"AC-8: motivo sin CASI {detail}"
    else:
        raise AssertionError("AC-8: 'CASI' no rechazo la fila")

    # d) plantilla SIN la columna importa OK (columnas None)
    etl = BudgetTemplates(_build_payroll_xlsx(None))
    etl.process_budget_plan_collaborators()
    recs = etl.dataframe_to_records()
    assert all(r["pays_pension"] is None for r in recs), \
        f"AC-8: sin columna => {recs}"


# ════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════

def main():
    engine_db = create_engine("sqlite://")  # in-memory, sin archivos
    Base.metadata.create_all(engine_db)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine_db)

    cases = [
        ("AC-1 pays_pension flag", case_ac1_pays_pension),
        ("AC-5 exonerated_lt100", case_ac5_exonerated),
        ("AC-6 custom liquidar_*", case_ac6_custom),
        ("AC-7 custom missing", case_ac7_custom_missing),
        ("AC-8 plantilla Cotiza pension", case_ac8_template),
    ]
    passed = failed = 0
    for label, fn in cases:
        db = Session()
        try:
            fn(db)
            passed += 1
            print(f"PASS {label}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {label}: {exc}")
            traceback.print_exc()
        finally:
            # persistir la semilla del caso para los siguientes (SQLite
            # in-memory shared: sin commit el close hace rollback).
            try:
                db.commit()
            except Exception:
                pass
            db.close()
            db = None
    print(f"{passed}/{len(cases)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
