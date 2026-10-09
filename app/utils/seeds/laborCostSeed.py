"""
Labor-cost seed (BE-S11-COLLABORATORS, backend.02_21 §4.8 fase 3)

Idempotent, natural-key, INSERT-only seed of the catalogs the motor
refuses to guess (D-S11-9):

    python -m app.utils.seeds.laborCostSeed

Seeds:
- cost_components: the §4.5 catalog (15 rows) — 9 CAJA legales,
  PRIMA/CESANTIAS/INTERESES/LIQ PROVISION legales and the two
  extralegales PRE_EXTRALEGAL / VAC_COMPENSATORIO seeded
  is_active=False (A-11/R-12: admin flips them on when they exist).
- labor_cost_parameters vigencia 2026 (all §4.3 keys).
- labor_arl_rates vigencia 2026 (classes I–V, §4.4).

NFR-03: the seed NEVER UPDATEs existing rows — parameters evolve only
via the audited PUT /budget/labor-params, so re-running after an admin
edit is harmless.

⚠ DEPLOYMENT RULE (§4.8 fase 3): the 2026 numbers below are the
FICTICIOS defaults of the spec document — NUNCA sembrar prod sin antes
la validación de contabilidad (DEP-01, BLOQUEANTE go-live).
"""

from decimal import Decimal

from app.db import Base, SessionLocal, engine
from app.models.budget import (
    CostComponent, LaborArlRate, LaborCostParameter,
)

VIGENCIA = 2026

# ──────────────────────────────────────────────────
# §4.5 catalog: (code, name, layer, formula_key, is_legal,
#               is_active, payment_date_key)
# ──────────────────────────────────────────────────
COST_COMPONENTS = [
    ("SAL", "Salario mensual", "CAJA",
     "salary+allowance_salary*factor", True, True, "dia_pago_salario"),
    ("C1S", "Honorarios (servicios)", "CAJA",
     "salary*factor", True, True, "dia_pago_servicios"),
    ("TRA", "Auxilio de transporte", "CAJA",
     "aux_transporte_valor*factor", True, True, "dia_pago_salario"),
    ("SALUD", "Seguridad social salud (8.5%)", "CAJA",
     "ibc*salud_patronal_pct", True, True, "dia_pago_salario"),
    ("PENSION", "Seguridad social pensión (12%)", "CAJA",
     "ibc*pension_pct", True, True, "dia_pago_salario"),
    ("ARL", "ARL (riesgo laboral)", "CAJA",
     "ibc*arl_rate", True, True, "dia_pago_salario"),
    ("CAJA", "Caja de compensación familiar", "CAJA",
     "base_caja*caja_pct", True, True, "dia_pago_salario"),
    ("SENA", "SENA", "CAJA",
     "ibc*sena_pct", True, True, "dia_pago_salario"),
    ("ICBF", "ICBF", "CAJA",
     "ibc*icbf_pct", True, True, "dia_pago_salario"),
    ("PRIMA", "Prima de servicios", "PROVISION",
     "base_prima*prima_tasa*factor", True, True,
     "fecha_prima_1,fecha_prima_2"),
    ("CESANTIAS", "Cesantías", "PROVISION",
     "base_ces*cesantias_tasa*factor", True, True, "fecha_cesantias"),
    ("INTERESES", "Intereses de cesantías", "PROVISION",
     "base_ces*intereses/12*factor", True, True, "fecha_intereses"),
    ("LIQ", "Liquidación (saldo provisiones)", "PROVISION",
     "saldo_provisiones", True, True, None),
    # Extralegales sembrados OFF (A-11/R-12): existen para que el admin
    # los active cuando apliquen, sin tocar código.
    ("PRE_EXTRALEGAL", "Prima extralegal", "PROVISION",
     "custom", False, False, None),
    ("VAC_COMPENSATORIO", "Compensatorio vacacional", "PROVISION",
     "custom", False, False, None),
]

# §4.3 vigencia 2026.
# ⚠ VALORES FICTICIOS — reemplazar tras DEP-01 (contabilidad)
LABOR_PARAMS = {
    "smlv": "1500000.00",
    "aux_transporte_valor": "150000.00",
    "aux_transporte_tope_smlv": "2",
    "salud_patronal_pct": "0.085000",
    "pension_pct": "0.120000",
    "caja_pct": "0.040000",
    "caja_tope_smlv": "2",
    "sena_pct": "0.020000",
    "icbf_pct": "0.030000",
    # DEP-01: a confirmar el régimen de exoneración por tamaño.
    "aplicacion_parafiscales": "all",
    "prima_tasa": "0.083333",
    "prima_tope_smlv_base": "2",
    "cesantias_tasa": "0.083333",
    "intereses_cesantias_anual": "0.120000",
    "integral_ibc_factor": "0.700000",
    "integral_tope_smlv": "25",
    "dia_pago_salario": "last_business_day",
    "dia_pago_servicios": "last_business_day",
    "fecha_prima_1": "06-30",
    "fecha_prima_2": "12-20",
    "fecha_intereses": "01-31",
    "fecha_cesantias": "02-14",
    "arl_default_class": "I",
}

# §4.4 vigencia 2026 (tasas res./Min.).
# ⚠ VALORES FICTICIOS — reemplazar tras DEP-01 (contabilidad)
ARL_RATES = {
    "I": Decimal("0.00522"),
    "II": Decimal("0.01044"),
    "III": Decimal("0.02436"),
    "IV": Decimal("0.04350"),
    "V": Decimal("0.06960"),
}


def seed_labor_cost(verbose: bool = True) -> dict:
    """INSERT-missing seed over the natural keys; never UPDATEs, never
    DELETEs (NFR-03). Returns the counters."""
    Base.metadata.create_all(bind=engine)  # fase 1 safety net (no-op
    # when the app already created the tables; NEVER alters)
    db = SessionLocal()
    counters = {"components": 0, "params": 0, "arl": 0}
    try:
        for row in COST_COMPONENTS:
            (code, name, layer, formula_key, is_legal, is_active,
             payment_date_key) = row
            exists = db.query(CostComponent).filter(
                CostComponent.code == code
            ).first()
            if exists is None:
                db.add(CostComponent(
                    code=code, name=name, layer=layer,
                    formula_key=formula_key, is_legal=is_legal,
                    is_active=is_active, payment_date_key=payment_date_key,
                ))
                counters["components"] += 1

        for key, value in LABOR_PARAMS.items():
            exists = db.query(LaborCostParameter).filter(
                LaborCostParameter.vigencia == VIGENCIA,
                LaborCostParameter.key == key,
            ).first()
            if exists is None:
                db.add(LaborCostParameter(
                    vigencia=VIGENCIA, key=key, value=value,
                ))
                counters["params"] += 1

        for risk_class, rate in ARL_RATES.items():
            exists = db.query(LaborArlRate).filter(
                LaborArlRate.vigencia == VIGENCIA,
                LaborArlRate.risk_class == risk_class,
            ).first()
            if exists is None:
                db.add(LaborArlRate(
                    vigencia=VIGENCIA, risk_class=risk_class, rate=rate,
                ))
                counters["arl"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if verbose:
        print(
            f"[laborCostSeed] vigencia {VIGENCIA}: "
            f"{counters['components']} componentes, "
            f"{counters['params']} parámetros, "
            f"{counters['arl']} tarifas ARL insertados "
            "(los existentes se conservan intactos — NFR-03)."
        )
    return counters


if __name__ == "__main__":
    seed_labor_cost()
