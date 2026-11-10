"""
Labor Cost Engine (BE-S11-COLLABORATORS, spec backend.02_21 §5)

Puro, sin HTTP, inyectable para test (§8): recibe ``db: Session`` y
parámetros y produce asientos ``(componente, capa, monto, budget_date,
payment_date, vigencia)``. No hace commit: el modo ``persist=True``
escribe a través de ``app.crud`` (flush) dentro de la MISMA transacción
del llamante (T-05 — import/recalculate/terminate hacen UN solo commit).

Materialization model (§5.2/§5.3/§7, reconciled with the §5.6 example):
  * CAJA layer  -> one seat per component per month, budget_date = fin
    de mes, payment_date = dia_pago_salario (last_business_day or a
    fixed day of month).
  * PROVISION
    causacion   -> seat AND budget_line: budget_date = fin del mes de
      causacion, payment_date = the LEGAL payment date of its period
      (prima ene-jun -> 30/06, jul-dic -> 20/12, intereses -> 31/01
      año sig, cesantias -> 14/02 año sig). Monthly P&L therefore sees
      the §5.6 "costo total del mes" and the cash flow aggregates the
      period's causes exactly on the legal date — which IS the payment
      seat's amount ("Σcausado − Σpagado", D-S11-3) without a second
      row. The payment seat itself is a LEDGER event: when the legal
      payment month falls inside a persist run the engine marks the
      period rows paid = accrued (never recomputed from the rate).
    liquidación -> the termination month turns every UNSETTLED accrued
      balance into a single LIQ seat (payment_date = termination_date,
      source_engine = collaborator_liquidation) and the unsettled
      causacion lines of those periods are replaced (not kept beside
      it — otherwise the settlement would double-count cash).

Money discipline (NFR-04/BR-06): Decimal end-to-end, ROUND_HALF_UP
quantized to 2 decimals ONLY per seat (§5); rates DECIMAL(9,6)/params
parsed from strings — cero float.

Vigencia resolution (R-05/BR-03/D-S11-9): the parameters of the seat's
calendar year are mandatory; a vigencia without rows (or missing a
needed key) raises ``MissingLaborParametersError`` → structured 400.
The motor NEVER guesses rates.
"""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import app.crud as crud
from app.models.budget import Collaborator
from app.models.budget.budgetLine import (
    BehaviorTypeEnum, LineTypeEnum,
)

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")

# Component codes of the §4.5 catalog used by the formulas.
C_SAL, C_C1S, C_TRA = "SAL", "C1S", "TRA"
C_SALUD, C_PENSION, C_ARL = "SALUD", "PENSION", "ARL"
C_CAJA, C_SENA, C_ICBF = "CAJA", "SENA", "ICBF"
C_PRIMA, C_CESANTIAS, C_INTERESES, C_LIQ = (
    "PRIMA", "CESANTIAS", "INTERESES", "LIQ",
)
ACCRUAL_CODES = (C_PRIMA, C_CESANTIAS, C_INTERESES)

ENGINE_COST = "collaborator_cost"
ENGINE_LIQUIDATION = "collaborator_liquidation"

_CONTRACT_SERVICE = "service_provision"

# Keys mandatory per contract flavor (§4.3). Missing key == missing
# vigencia for the motor (R-05: it never guesses). backend.02_27 adds
# three MODE-ONLY keys read just in their applicacion_parafiscales
# branch (NOT mandatory globally — "all" runs fine without them):
#   * parafiscales_tope_exoneracion_smlv  (exonerated_lt100, §6.2)
#   * liquidar_caja / liquidar_sena / liquidar_icbf  (custom, "1"/"0")
_DEPENDENT_KEYS = (
    "smlv", "aux_transporte_valor", "aux_transporte_tope_smlv",
    "salud_patronal_pct", "pension_pct", "caja_pct", "caja_tope_smlv",
    "sena_pct", "icbf_pct", "aplicacion_parafiscales",
    "prima_tasa", "prima_tope_smlv_base", "cesantias_tasa",
    "intereses_cesantias_anual", "integral_ibc_factor",
    "integral_tope_smlv", "dia_pago_salario",
    "fecha_prima_1", "fecha_prima_2", "fecha_intereses", "fecha_cesantias",
    "arl_default_class",
)
_SERVICE_KEYS = ("dia_pago_servicios",)

# Required catalog (§4.5 seed, fase 3 §4.8).
_REQUIRED_CATALOG = (
    C_SAL, C_C1S, C_TRA, C_SALUD, C_PENSION, C_ARL, C_CAJA, C_SENA,
    C_ICBF, C_PRIMA, C_CESANTIAS, C_INTERESES, C_LIQ,
)


def q2(value: Decimal) -> Decimal:
    """NFR-04: cuantización a 2 decimales ROUND_HALF_UP, aplicada SOLO
    por asiento (las bases se propagan sin redondear, §5)."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class MissingLaborParametersError(Exception):
    """R-05/BR-03/D-S11-9: the vigencia required by a seat has zero
    parameters (or lacks a mandatory key). The API converts it into a
    400 carrying the missing vigencia; the surrounding transaction
    rolls everything back (T-05: 0 líneas, AC-CFG-1)."""

    def __init__(self, vigencia: int, key: Optional[str] = None):
        self.vigencia = vigencia
        self.key = key
        if key is None:
            msg = (
                f"Labor parameters missing for vigencia {vigencia}: "
                "configure them via PUT /budget/labor-params before "
                "projecting payroll costs (R-05)"
            )
        else:
            msg = (
                f"Labor parameter '{key}' missing for vigencia "
                f"{vigencia} (R-05: the motor never guesses rates)"
            )
        super().__init__(msg)


class CostCatalogIncompleteError(Exception):
    """§4.5 seed (fase 3) not applied or partially deleted: the motor
    refuses to invent catalog rows; the API answers 400 (AC-DEP-1)."""

    def __init__(self, missing: List[str]):
        self.missing = sorted(missing)
        super().__init__(
            "cost_components catalog is missing codes: "
            + ", ".join(self.missing)
            + " — apply the seed app.utils.seeds.laborCostSeed"
        )


@dataclass
class Asiento:
    """One motor seat (§5 salida). amount is already q2()'d;
    source_engine ∈ {collaborator_cost, collaborator_liquidation}."""
    component_code: str
    layer: str
    amount: Decimal
    budget_date: date
    payment_date: date
    vigencia: int
    source_engine: str
    kind: str = "caja"  # caja | accrual | liquidation
    # For liquidation seats: the accrued component whose unsettled
    # balance this LIQ seat absorbs (description context only).
    liq_for: Optional[str] = None


@dataclass
class EngineRunResult:
    """Aggregated outcome of one run (import/recalculate/terminate)."""
    created_lines: int = 0
    deleted_lines: int = 0
    months_processed: int = 0
    not_materialized: int = 0
    warnings: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────
# Calendar helpers
# ──────────────────────────────────────────────────

def _month_bounds(month_first: date) -> Tuple[date, date]:
    """(1st, last) day of the month containing month_first."""
    last = monthrange(month_first.year, month_first.month)[1]
    return date(month_first.year, month_first.month, 1), date(
        month_first.year, month_first.month, last
    )


def _add_months(month_first: date, n: int) -> date:
    total = (month_first.year * 12 + (month_first.month - 1)) + n
    return date(total // 12, total % 12 + 1, 1)


def _last_business_day(year: int, month: int) -> date:
    """día hábil = Mon–Fri (no festarios: OQ-BE-1 — the parameter takes
    'last_business_day' or a fixed day-of-month; holidays need no code
    change)."""
    last = date(year, month, monthrange(year, month)[1])
    while last.weekday() >= 5:  # 5=Sat 6=Sun
        last = date(last.year, last.month, last.day - 1)
    return last


def _pay_day(value: str, year: int, month: int) -> date:
    """dia_pago_salario / dia_pago_servicios parameter: literal
    'last_business_day' or a fixed day-of-month number (clamped to the
    real month length)."""
    text = str(value).strip().lower()
    if text in ("last_business_day", "ultimo_habil", "ultimo habil"):
        return _last_business_day(year, month)
    try:
        day = int(float(text))
    except (TypeError, ValueError):
        day = monthrange(year, month)[1]
    return date(year, month, min(max(day, 1), monthrange(year, month)[1]))


def _mmdd(value: str, fallback: Tuple[int, int]) -> Tuple[int, int]:
    """Parse a 'MM-DD' parameter (fecha_prima_1 etc.); anything
    unparseable falls back to the legal default (the seed always writes
    a valid value — defensive only, never a rate guess)."""
    text = str(value).strip()
    try:
        mm, dd = text.split("-")
        month, day = int(mm), int(dd)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day
    except (ValueError, AttributeError):
        pass
    return fallback


# ──────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────

class LaborCostEngine:
    """Pure-DB motor (no HTTP, no commit — the caller owns T-05)."""

    def __init__(self, db: Session):
        self.db = db
        self._params_cache: Dict[int, Dict[str, str]] = {}
        self._catalog: Optional[Dict[str, object]] = None
        self._budget_cache: Dict[int, Optional[object]] = {}
        # LIQ causacion lines replaced during the current run (folded
        # into EngineRunResult.deleted_lines by run_projection). The
        # deferred list is collected during compute (the month's own
        # causacion seats are only INSERTED after the whole month is
        # computed, so the replacement delete must run post-insert).
        self._liq_replaced: List[str] = []
        self._liq_cleaned = 0
        self._liq_pending: List[Tuple[str, List[date]]] = []

    # ── catalogs / params (cached per run) ─────────

    def _raw_params(self, vigencia: int) -> Dict[str, str]:
        if vigencia not in self._params_cache:
            rows = crud.get_labor_parameters(self.db, vigencia)
            self._params_cache[vigencia] = {r.key: r.value for r in rows}
        return self._params_cache[vigencia]

    def _param(self, vigencia: int, key: str) -> str:
        params = self._raw_params(vigencia)
        if not params:
            raise MissingLaborParametersError(vigencia)
        value = params.get(key)
        if value is None or str(value).strip() == "":
            raise MissingLaborParametersError(vigencia, key)
        return str(value)

    def _param_dec(self, vigencia: int, key: str) -> Decimal:
        return Decimal(self._param(vigencia, key))

    def _components(self) -> Dict[str, object]:
        if self._catalog is None:
            catalog = crud.get_cost_component_map(self.db)
            missing = [
                code for code in _REQUIRED_CATALOG if code not in catalog
            ]
            if missing:
                raise CostCatalogIncompleteError(missing)
            self._catalog = catalog
        return self._catalog

    def _comp(self, code: str):
        return self._components()[code]

    def _active(self, code: str) -> bool:
        comp = self._comp(code)
        return bool(getattr(comp, "is_active", True))

    def _name(self, code: str) -> str:
        return str(getattr(self._comp(code), "name", code))

    def _layer(self, code: str) -> str:
        return str(getattr(self._comp(code), "layer", "CAJA"))

    def _active_budget(self, year: int):
        if year not in self._budget_cache:
            self._budget_cache[year] = crud.get_active_budget_for_year(
                self.db, year
            )
        return self._budget_cache[year]

    # ── §5.1 bases ─────────────────────────────────

    @staticmethod
    def _plan_for_month(plans, m_first: date, m_last: date):
        """The plan vigente in the month: the latest valid_from
        overlapping it. A mid-month raise applies the NEW plan to the
        whole month (v1 reading of "el plan vigente ese mes"; day-level
        splits are only mandated for hire/termination, BR-12)."""
        candidates = [
            p for p in plans
            if p.valid_from <= m_last
            and (p.valid_to is None or p.valid_to >= m_first)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.valid_from)

    @staticmethod
    def _prorate_factor(collab: Collaborator, m_first: date,
                        m_last: date) -> Decimal:
        """BR-CALC-06/BR-12: días causados (calendar) / días del mes.
        1.0 on complete months, 0 beyond hire/termination (R-11/BR-07)."""
        lo = max(collab.hire_date, m_first)
        hi = m_last
        if collab.termination_date is not None:
            hi = min(hi, collab.termination_date)
        if hi < lo:
            return ZERO
        days = (hi - lo).days + 1
        total = (m_last - m_first).days + 1
        if days >= total:
            return Decimal("1")
        return Decimal(days) / Decimal(total)

    def _bases(self, collab: Collaborator, plan,
               vigencia: int) -> Dict[str, Decimal]:
        """IBC / base_prima / base_ces / base_caja (§5.1).
        allowance_non_salary NEVER enters (BR-11): integral "total_plan"
        = salario + asignación salarial (A-06)."""
        salary = Decimal(plan.salary or 0)
        al_sal = Decimal(plan.allowance_salary or 0)

        ibc_regular = salary + al_sal
        smlv = self._param_dec(vigencia, "smlv")
        if plan.is_integral:
            factor = self._param_dec(vigencia, "integral_ibc_factor")
            tope = self._param_dec(vigencia, "integral_tope_smlv")
            ibc = min(ibc_regular * factor, tope * smlv)
        else:
            ibc = ibc_regular

        base_prima = min(
            ibc, self._param_dec(vigencia, "prima_tope_smlv_base") * smlv
        )
        base_ces = ibc  # cesantías sin tope legal por defecto (§5.1)
        base_caja = min(ibc, self._param_dec(vigencia, "caja_tope_smlv") * smlv)

        return {
            "salary": salary,
            "allowance_salary": al_sal,
            "allowance_non_salary": Decimal(plan.allowance_non_salary or 0),
            "ibc": ibc,
            "base_prima": base_prima,
            "base_ces": base_ces,
            "base_caja": base_caja,
        }

    # ── legal payment dates of the PROVISION periods (§5.3) ──

    def _legal_pay_dates(self, y: int) -> Dict[str, List[Tuple[int, int, date]]]:
        """[(period_month_from, period_month_to, payment_date)] per
        component for causes accrued in year y (or y-1 for the annual
        ones paid in y). Drives BOTH the causacion seat's payment_date
        and the ledger settlement month."""
        prima1 = _mmdd(self._param(y, "fecha_prima_1"), (6, 30))
        prima2 = _mmdd(self._param(y, "fecha_prima_2"), (12, 20))
        interes = _mmdd(self._param(y, "fecha_intereses"), (1, 31))
        cesan = _mmdd(self._param(y, "fecha_cesantias"), (2, 14))
        pay1 = date(y, prima1[0], prima1[1])
        pay2 = date(y, prima2[0], prima2[1])
        # §4.3: intereses (31/01) y cesantías (14/02) se pagan en el AÑO
        # SIGUIENTE con el MM-DD de la vigencia de la causación.
        pay_int = date(y + 1, interes[0], interes[1])
        pay_ces = date(y + 1, cesan[0], cesan[1])
        return {
            # component -> [(accrual month, legal pay date)] for the
            # periods whose causes fall in year y.
            C_PRIMA: [
                (m, pay1) for m in range(1, 7)
            ] + [
                (m, pay2) for m in range(7, 13)
            ],
            # intereses/cesantías accrued during year y are paid in the
            # LEGAL MONTHS OF y+1 under the params of y (§4.3 "año
            # siguiente"): settlement month resolved per run below.
            C_INTERESES: [(m, pay_int) for m in range(1, 13)],
            C_CESANTIAS: [(m, pay_ces) for m in range(1, 13)],
        }

    # ── ledger helpers ─────────────────────────────

    def _period_rows(
        self, collab_id: int, code: str,
        period_from: date, period_to: date,
        exclude_month: Optional[date] = None,
    ):
        rows = crud.accruals_in_range(
            self.db, collab_id, code,
            _month_bounds(period_from)[0], _month_bounds(period_to)[0],
        )
        if exclude_month is not None:
            rows = [r for r in rows if r.period_month != exclude_month]
        return rows

    def _period_balance(
        self, collab_id: int, code: str,
        period_from: date, period_to: date,
        exclude_month: Optional[date] = None,
        extra_amount: Decimal = ZERO,
    ) -> Decimal:
        """Σcausado − Σpagado del periodo (§5.3: el pago JAMÁS se
        recalcula desde la tarifa, D-S11-3). extra_amount adds the
        CURRENT month's causacion when persist=False (the row is not in
        the ledger yet; in persist mode the row was upserted BEFORE the
        settlement is computed, so it already participates in the sum)."""
        rows = self._period_rows(
            collab_id, code, period_from, period_to, exclude_month
        )
        balance = sum(
            (Decimal(r.accrued) - Decimal(r.paid) for r in rows), ZERO
        )
        if exclude_month is not None and _month_bounds(period_from)[0] \
                <= exclude_month <= _month_bounds(period_to)[0]:
            balance += Decimal(extra_amount)
        return balance

    # ── month core ─────────────────────────────────

    def _description(self, collab: Collaborator, label: str) -> str:
        """§7 format: "{Componente} — {full_name} ({doc_value})"."""
        return f"{label} — {collab.full_name} ({collab.doc_value})"

    def compute_month(
        self, collab: Collaborator, month_first: date, persist: bool = True,
    ) -> List[Asiento]:
        """Seats of ONE month for ONE collaborator (§5). With
        persist=False nothing is written: causacion and settlement
        marks are simulated in-memory (breakdown endpoint); the
        returned seats are identical to what a persist run would
        materialize for that month."""
        m_first, m_last = _month_bounds(month_first)
        y, mo = m_first.year, m_first.month
        asiento_list: List[Asiento] = []

        plans = crud.get_salary_plans(self.db, collab.id_collaborator)
        plan = self._plan_for_month(plans, m_first, m_last)
        if plan is None:
            return asiento_list

        # R-11/BR-07: meses > término => cero asientos (run_projection
        # already deleted the month's stale engine lines before calling).
        if collab.termination_date is not None and m_first > _month_bounds(
            collab.termination_date
        )[0]:
            return asiento_list

        # Mandatory-key guard per contract flavor (also validates the
        # vigencia exists — _param raises MissingLaborParametersError).
        keys = _SERVICE_KEYS if collab.contract_type == _CONTRACT_SERVICE \
            else _DEPENDENT_KEYS
        for key in keys:
            self._param(y, key)

        factor = self._prorate_factor(collab, m_first, m_last)
        if factor == ZERO:
            return asiento_list

        # ── §5.4 prestación de servicios: único asiento C1S ──
        if collab.contract_type == _CONTRACT_SERVICE:
            if not self._active(C_C1S):
                return asiento_list
            pago_serv = _pay_day(self._param(y, "dia_pago_servicios"), y, mo)
            amount = q2(Decimal(plan.salary or 0) * factor)
            if amount > ZERO:
                asiento_list.append(Asiento(
                    component_code=C_C1S,
                    layer=self._layer(C_C1S),
                    amount=amount,
                    budget_date=m_last,
                    payment_date=pago_serv,
                    vigencia=y,
                    source_engine=ENGINE_COST,
                    kind="caja",
                ))
            return asiento_list

        pago_salario = _pay_day(self._param(y, "dia_pago_salario"), y, mo)
        bases = self._bases(collab, plan, y)
        terminated_in_month = (
            collab.termination_date is not None
            and m_first <= collab.termination_date <= m_last
        )

        # ── §5.2 capa CAJA ─────────────────────────
        caja = [(C_SAL, q2((bases["salary"] + bases["allowance_salary"]) * factor))]

        aux_valor = self._param_dec(y, "aux_transporte_valor")
        aux_tope = self._param_dec(y, "aux_transporte_tope_smlv")
        smlv = self._param_dec(y, "smlv")
        if (bases["salary"] + bases["allowance_salary"]) <= aux_tope * smlv:
            # auxilio de transporte: condicional al tope; nunca base de
            # prestaciones (solo entra en su propio asiento, §5.2).
            caja.append((C_TRA, q2(aux_valor * factor)))

        caja.append((C_SALUD, q2(bases["ibc"] * self._param_dec(y, "salud_patronal_pct"))))
        # backend.02_27 §6.1: the employer pension seat is governed by
        # the collaborator's own flag (default True — old rows without
        # the column keep today's behavior). It does NOT touch SAL /
        # SALUD / ARL / CAJA / aux / provisions.
        if getattr(collab, "pays_pension", True):
            caja.append((C_PENSION, q2(bases["ibc"] * self._param_dec(y, "pension_pct"))))

        risk_class = collab.risk_class or self._param(y, "arl_default_class")
        arl_rates = crud.get_labor_arl_rates(self.db, y)
        rate = arl_rates.get(str(risk_class).strip().upper()[:1])
        if rate is None:
            # §4.4: ARL rates are part of the vigencia — R-05 with the
            # class context (the motor never guesses).
            raise MissingLaborParametersError(y, f"arl_rate[{risk_class}]")
        caja.append((C_ARL, q2(bases["ibc"] * Decimal(rate))))

        # ── Parafiscales (backend.02_27 §6.2 matrix) ──
        # all              -> SENA + ICBF + CAJA
        # exonerated_lt100 -> CAJA always; SENA/ICBF only when
        #                     ibc >= parafiscales_tope_exoneracion_smlv
        #                     * smlv (per collaborator; the tope is read
        #                     ONLY in this mode — R-05 if missing).
        # custom           -> each of CAJA/SENA/ICBF per its liquidar_*
        #                     key ("1"/"0", read ONLY in this mode —
        #                     R-05 if missing).
        aplicacion = self._param(y, "aplicacion_parafiscales").strip().lower()
        caja_pct = self._param_dec(y, "caja_pct")
        if aplicacion == "exonerated_lt100":
            tope = self._param_dec(y, "parafiscales_tope_exoneracion_smlv")
            caja.append((C_CAJA, q2(bases["base_caja"] * caja_pct)))
            if bases["ibc"] >= tope * smlv:
                caja.append((C_SENA, q2(bases["ibc"] * self._param_dec(y, "sena_pct"))))
                caja.append((C_ICBF, q2(bases["ibc"] * self._param_dec(y, "icbf_pct"))))
        elif aplicacion == "custom":
            if self._param(y, "liquidar_caja") == "1":
                caja.append((C_CAJA, q2(bases["base_caja"] * caja_pct)))
            if self._param(y, "liquidar_sena") == "1":
                caja.append((C_SENA, q2(bases["ibc"] * self._param_dec(y, "sena_pct"))))
            if self._param(y, "liquidar_icbf") == "1":
                caja.append((C_ICBF, q2(bases["ibc"] * self._param_dec(y, "icbf_pct"))))
        else:
            # "all" (and any unexpected value: the motor keeps the
            # inclusive default instead of dropping components).
            caja.append((C_CAJA, q2(bases["base_caja"] * caja_pct)))
            caja.append((C_SENA, q2(bases["ibc"] * self._param_dec(y, "sena_pct"))))
            caja.append((C_ICBF, q2(bases["ibc"] * self._param_dec(y, "icbf_pct"))))

        for code, amount in caja:
            if self._active(code) and amount > ZERO:
                asiento_list.append(Asiento(
                    component_code=code, layer=self._layer(code),
                    amount=amount, budget_date=m_last,
                    payment_date=pago_salario, vigencia=y,
                    source_engine=ENGINE_COST, kind="caja",
                ))

        # ── §5.3 causación PROVISION (asiento + ledger) ──
        # Each cause becomes a monthly PROVISION line whose payment_date
        # is the LEGAL date of its period (§5.6 "costo total del mes":
        # P&L mensual correcto; el flujo de caja agrega el periodo
        # exactamente en su fecha legal == el "asiento de pago"
        # Σcausado−Σpagado, D-S11-3, sin fila duplicada).
        legal = self._legal_pay_dates(y)
        causes = {
            C_PRIMA: q2(bases["base_prima"] * self._param_dec(y, "prima_tasa") * factor),
            C_CESANTIAS: q2(bases["base_ces"] * self._param_dec(y, "cesantias_tasa") * factor),
            C_INTERESES: q2(
                bases["base_ces"] * self._param_dec(y, "intereses_cesantias_anual")
                / Decimal("12") * factor
            ),
        }
        for code, amount in causes.items():
            if not self._active(code):
                continue
            pay_date = self._legal_pay_for_month(code, mo, legal)
            if amount > ZERO:
                asiento_list.append(Asiento(
                    component_code=code, layer=self._layer(code),
                    amount=amount, budget_date=m_last,
                    payment_date=pay_date, vigencia=y,
                    source_engine=ENGINE_COST, kind="accrual",
                ))
            if persist and amount > ZERO:
                crud.upsert_provision_accrual(
                    self.db, collab.id_collaborator, code, m_first,
                    amount, y,
                )

        # In-memory ledger view for persist=False (breakdown): the
        # current month's causes must join the settlement sums below.
        sim_month = None if persist else m_first

        # ── §5.5 liquidación vs cierre legal del mes (§5.3) ──
        if terminated_in_month:
            asiento_list.extend(self._liquidation_seats(
                collab, causes, m_last, sim_month, persist,
            ))
            # Regla §5.3: en el mes del término el saldo pasa a LIQ —
            # el cierre regular de ese mes NO ocurre (ya lo hace LIQ).
            return asiento_list

        # Cierre de ledger en los meses legales de pago (solo con
        # persist=True; la caja del asiento de pago NO es línea: las
        # líneas de causación YA llevan la fecha legal de pago).
        if persist:
            self._settle_legal_periods(collab, y, mo)
        return asiento_list

    @staticmethod
    def _legal_pay_for_month(code: str, month: int, legal) -> date:
        """The legal payment date of the period containing ``month``."""
        for m, pay in legal[code]:
            if m == month:
                return pay
        # unreachable with a sane §4.3 map; deterministic fallback
        return legal[code][-1][1]

    def _settle_legal_periods(
        self, collab: Collaborator, y: int, month: int
    ) -> None:
        """Ledger closure in the LEGAL payment months (§5.3, D-S11-3):
        prima cierra ene–jun al 30/06 y jul–dic al 20/12; intereses al
        31/01 y cesantías al 14/02 del AÑO SIGUIENTE cierran el año
        natural anterior. paid = accrued exacto — jamas se recalcula
        desde la tarifa. The run reset (_reset_marks_for_window) cleared
        these marks beforehand whenever the payment month falls inside
        the window, so re-runs are idempotent."""
        legal = self._legal_pay_dates(y)
        # prima: month == payment month of the semester
        for code, period, pay in (
            (C_PRIMA, (date(y, 1, 1), date(y, 6, 30)), legal[C_PRIMA][0][1]),
            (C_PRIMA, (date(y, 7, 1), date(y, 12, 31)), legal[C_PRIMA][6][1]),
            # intereses/cesantías accrued in y-1 pay in y (params of y
            # carry the legal MM-DD; _legal_pay_dates(y) built them with
            # the dates of year y itself which is exactly y's January/
            # February settlement).
            (C_INTERESES, (date(y - 1, 1, 1), date(y - 1, 12, 31)),
             self._settlement_date(y, "fecha_intereses", (1, 31))),
            (C_CESANTIAS, (date(y - 1, 1, 1), date(y - 1, 12, 31)),
             self._settlement_date(y, "fecha_cesantias", (2, 14))),
        ):
            if month != pay.month or not self._active(code):
                continue
            rows = self._period_rows(collab.id_collaborator, code, *period)
            if rows:
                crud.mark_accruals_paid(self.db, rows)

    def _settlement_date(self, y: int, key: str,
                         fallback: Tuple[int, int]) -> date:
        mm, dd = _mmdd(self._param(y, key), fallback)
        return date(y, mm, dd)

    # ── §5.5 liquidación ───────────────────────────

    def _liquidation_seats(
        self, collab: Collaborator,
        causes: Dict[str, Decimal], m_last: date,
        sim_month: Optional[date], persist: bool,
    ) -> List[Asiento]:
        """Saldo ACUMULADO (no pagado) de PRIMA/CESANTIAS/INTERESES tras
        la causación del mes del término => asiento LIQ por componente
        (capa PROVISION, payment_date = termination_date,
        source_engine = collaborator_liquidation). Las líneas de
        causación EN LIQUIDACIÓN de esos periodos se reemplazan (de lo
        contrario el cash-flow pagaría dos veces el mismo semestre)."""
        seats: List[Asiento] = []
        term = collab.termination_date
        if term is None or not self._active(C_LIQ):
            return seats
        y = term.year
        for code in ACCRUAL_CODES:
            if not self._active(code):
                continue
            balance = self._period_balance(
                collab.id_collaborator, code,
                date(1900, 1, 1), date(2999, 12, 31),
                exclude_month=sim_month,
                extra_amount=causes.get(code, ZERO) if sim_month else ZERO,
            )
            amount = q2(balance)
            if amount <= ZERO:
                continue
            seats.append(Asiento(
                component_code=C_LIQ, layer=self._layer(C_LIQ),
                amount=amount, budget_date=m_last, payment_date=term,
                vigencia=y, source_engine=ENGINE_LIQUIDATION,
                kind="liquidation", liq_for=code,
            ))
            if persist:
                unsettled_months = [
                    r.period_month for r in self._period_rows(
                        collab.id_collaborator, code,
                        date(1900, 1, 1), date(2999, 12, 31),
                    )
                    if Decimal(r.accrued) > Decimal(r.paid)
                ]
                # AC-LIQ-1: paid == accrued tras el cierre (saldo 0).
                crud.mark_accruals_paid(self.db, self._period_rows(
                    collab.id_collaborator, code,
                    date(1900, 1, 1), date(2999, 12, 31),
                ))
                # Las líneas de causación que el LIQ absorbe NO se
                # borran aquí: las del propio mes del término aún no
                # están insertadas. run_projection ejecuta el reemplazo
                # después de insertar el mes (self._liq_pending).
                if unsettled_months:
                    self._liq_replaced.append(code)
                    self._liq_pending.append(
                        (code, sorted(set(unsettled_months)))
                    )
        return seats

    def _liq_clean_months(
        self, collab_id: int, code: str, months: List[date]
    ) -> None:
        """Delete the motor's causacion LINES of the unsettled months of
        one component (the LIQ seat replaces them). Rows of months that
        were never materialized simply no-op. Counted into the run's
        deleted_lines via self._liq_cleaned."""
        cleaned = crud.delete_collaborator_engine_component_months(
            self.db, collab_id, code, months
        )
        self._liq_cleaned += cleaned

    # ── window projection (import/recalculate/terminate) ──

    def run_projection(
        self,
        collab: Collaborator,
        start_first: date,
        end_last: date,
    ) -> EngineRunResult:
        """Motor run over the closed month window [start_first ..
        end_last] with the R-13 idempotent replacement PER MONTH:
        delete the collaborator's motor-owned lines + causacion rows of
        the month, recompute and re-insert — manual lines, other
        templates and the REAL side stay untouched (BR-09/BR-13).

        Termination handling: when the collaborator has a
        termination_date inside the load YEAR, the window is extended
        back to January 1st so the settlement and every legal closure
        it interacts with are rebuilt consistently. Ledger ``paid``
        marks of periods whose payment month falls inside the run are
        RESET beforehand (the recreated seats/periods re-set them);
        marks of periods outside the window belong to lines that
        survive untouched."""
        result = EngineRunResult()
        self._liq_replaced = []
        self._liq_cleaned = 0
        self._liq_pending = []
        start_first, _ = _month_bounds(start_first)
        end_first, end_last = _month_bounds(end_last)

        if collab.termination_date is not None:
            term_month_first, _ = _month_bounds(collab.termination_date)
            if (term_month_first.year == start_first.year
                    and term_month_first < start_first):
                start_first = date(start_first.year, 1, 1)

        self._reset_marks_for_window(collab, start_first, end_first)

        cursor = start_first
        while cursor <= end_first:
            m_first, m_last = _month_bounds(cursor)
            result.deleted_lines += crud.delete_collaborator_engine_lines(
                self.db, collab.id_collaborator, m_first, m_last
            )
            crud.delete_provision_accruals_for_month(
                self.db, collab.id_collaborator, m_first
            )
            seats = self.compute_month(collab, m_first, persist=True)
            result.months_processed += 1

            rows: List[Dict] = []
            for seat in seats:
                label = self._name(seat.component_code)
                if seat.kind == "liquidation":
                    label = f"Liquidación (saldo {seat.liq_for})"
                budget = self._active_budget(seat.budget_date.year)
                if budget is None:
                    # D-S11-8 fallback: no active scenario for the seat
                    # year — the causacion ledger keeps its truth but a
                    # budget_line has no id_budget to point at (NOT NULL).
                    result.not_materialized += 1
                    continue
                rows.append({
                    "id_budget": budget.id_budget,
                    "id_cost_center": collab.id_cost_center,
                    # Enum MEMBERS (not the raw "expense"/"fixed" value
                    # strings): the Postgres enum bind resolves names,
                    # and every existing call-site reaches these columns
                    # through the pydantic BudgetLineCreate schema which
                    # already coerces value->member. The engine builds
                    # model dicts directly, so it coerces the same way.
                    "line_type": LineTypeEnum.EXPENSE,
                    "behavior_type": BehaviorTypeEnum.FIXED,
                    "budget_date": seat.budget_date,
                    "payment_date": seat.payment_date,
                    "id_collection": collab.id_collection,
                    "projected_amount": seat.amount,
                    # IVA fix 2026-10-26: payroll never bears VAT (D-S10-3
                    # semantics — NULL would be read as "con IVA" by the
                    # liquidation engine and the flow view's gross-up). The
                    # materialized lines now enter with an EXPLICIT False so
                    # every consumer (E2 emission, budget engine, FE flow)
                    # keeps salary/benefits/liquidation net.
                    "has_iva": False,
                    "description": self._description(collab, label),
                    "id_collaborator": collab.id_collaborator,
                    "cost_component_code": seat.component_code,
                    "source_engine": seat.source_engine,
                })
            result.created_lines += crud.insert_collaborator_engine_lines(
                self.db, rows
            )
            # Post-insert replacement (deferred by the LIQ seats above):
            # drop the unsettled causacion lines the LIQ absorbed —
            # including this same month's, which did not exist at
            # compute time.
            if self._liq_pending:
                for code, months in self._liq_pending:
                    self._liq_clean_months(
                        collab.id_collaborator, code, months
                    )
                self._liq_pending = []
            cursor = _add_months(cursor, 1)

        result.deleted_lines += self._liq_cleaned

        if result.not_materialized:
            result.warnings.append(
                f"{result.not_materialized} seat(s) not materialized: no "
                "active scenario for their year (accruals ledger kept — "
                "POST /budget/planning/{id}/set-target then "
                "POST /budget/collaborator/recalculate)"
            )
        return result

    def _reset_marks_for_window(
        self, collab: Collaborator, start_first: date, end_first: date
    ) -> None:
        """Clear the ledger ``paid`` marks of every payment period whose
        payment date falls inside [start_first .. end_first] (those
        periods are about to be re-caused / re-closed by the run), and —
        when the run reaches the termination month — ALL marks (the LIQ
        seat re-pays the remaining balance). Years whose params are
        absent are skipped: compute_month raises the proper R-05 only
        for months that actually need a vigencia."""
        for year in range(start_first.year, end_first.year + 1):
            try:
                legal = self._legal_pay_dates(year)
            except MissingLaborParametersError:
                continue
            # prima semestres + annual closes paid in legal months of
            # `year` over periods of year-1.
            spans = [
                (C_PRIMA, date(year, 1, 1), date(year, 6, 30),
                 legal[C_PRIMA][0][1]),
                (C_PRIMA, date(year, 7, 1), date(year, 12, 31),
                 legal[C_PRIMA][6][1]),
                (C_INTERESES, date(year - 1, 1, 1), date(year - 1, 12, 31),
                 self._settlement_date(year, "fecha_intereses", (1, 31))),
                (C_CESANTIAS, date(year - 1, 1, 1), date(year - 1, 12, 31),
                 self._settlement_date(year, "fecha_cesantias", (2, 14))),
            ]
            for code, p_from, p_to, pay in spans:
                pay_first, _ = _month_bounds(pay)
                if start_first <= pay_first <= end_first:
                    crud.reset_accruals_paid(self.db, self._period_rows(
                        collab.id_collaborator, code, p_from, p_to,
                    ))
        if (collab.termination_date is not None
                and start_first
                <= _month_bounds(collab.termination_date)[0] <= end_first):
            crud.reset_all_accruals_paid(self.db, collab.id_collaborator)

    # ── read-only derivation (breakdown endpoint) ──

    def breakdown(
        self, collab: Collaborator, month_first: date
    ) -> Dict:
        """§9 contract: {month, components[], total_caja,
        total_provision, params_vigencia} — pure read (persist=False);
        the seats are what the motor materializes for that month
        (AC-INT-2: Σ CAJA + Σ PROVISION del breakdown == Σ líneas del
        motor del mes, y por tanto del año)."""
        m_first, _ = _month_bounds(month_first)
        seats = self.compute_month(collab, m_first, persist=False)
        components = []
        total_caja = ZERO
        total_provision = ZERO
        for seat in seats:
            components.append({
                "code": seat.component_code,
                "name": self._name(seat.component_code),
                "layer": seat.layer,
                "amount": seat.amount,
                "payment_date": seat.payment_date,
                "kind": seat.kind,
                "liq_for": seat.liq_for,
            })
            if seat.layer == "CAJA":
                total_caja += seat.amount
            else:
                total_provision += seat.amount
        return {
            "id_collaborator": collab.id_collaborator,
            "month": f"{m_first.year}-{m_first.month:02d}",
            "components": components,
            "total_caja": q2(total_caja),
            "total_provision": q2(total_provision),
            "params_vigencia": m_first.year,
        }

    # ── scenario simulation (payroll what-if, BE-S11 extension) ──

    def simulate_year(self, year: int) -> Dict:
        """Nomina what-if de un escenario NO activo: lectura pura, CERO
        escrituras (misma ruta persist=False del breakdown, AC-SIM-4).
        Ene-Dic sobre list_active_collaborators — el MISMO set que
        materialize_for_scenario_year usa al activar — de modo que lo
        que ve el usuario en un borrador es exactamente lo que se
        materializaria al marcarlo meta (invariante Opcion C intacto).

        Cada dict de lines espeja la budget_line que run_projection
        crearia (amount, description y fechas identicos) sin
        id_budget_line: el FE las marca is_simulated y la guarda D-FE15-7
        (source_engine colaborator_*) les niega edicion/borrado."""
        collabs = crud.list_active_collaborators(self.db)
        lines: List[Dict] = []
        total = ZERO
        cursor = date(year, 1, 1)
        for _ in range(12):
            m_first, _m_last = _month_bounds(cursor)
            for collab in collabs:
                for seat in self.compute_month(collab, m_first, persist=False):
                    label = self._name(seat.component_code)
                    if seat.kind == "liquidation":
                        label = f"Liquidación (saldo {seat.liq_for})"
                    amount = q2(seat.amount)
                    lines.append({
                        "month": f"{m_first.year}-{m_first.month:02d}",
                        "budget_date": seat.budget_date,
                        "payment_date": seat.payment_date,
                        "id_cost_center": collab.id_cost_center,
                        "id_collection": collab.id_collection,
                        "cost_component_code": seat.component_code,
                        "component_name": label,
                        "layer": seat.layer,
                        "kind": seat.kind,
                        "description": self._description(collab, label),
                        "amount": amount,
                        "id_collaborator": collab.id_collaborator,
                        "collaborator_name": collab.full_name,
                    })
                    total += amount
            cursor = _add_months(cursor, 1)
        return {
            "year": year,
            "collaborators_count": len(collabs),
            "total_annual": q2(total),
            "lines": lines,
        }

    # ── window resolution (D-S11-8) ────────────────

    def resolve_window(
        self, collab: Collaborator, load_month: date
    ) -> Tuple[date, date]:
        """[mes de carga, ajustado a la vigencia mas antigua de los
        planes (se atrasa si es futura; se retrotrae si es anterior
        dentro del ano del escenario, floor 01/01 — A-10 nunca re-toca
        anos pasados) .. 31/12 del budget_year del escenario activo — o
        31/12 del ano natural sin escenario]. The termination cut is
        NOT applied here: months after the term run with zero seats
        (R-11) but MUST still be cleaned by the R-13 replacement; a
        past termination inside the same year is extended backwards by
        run_projection so its settlement (LIQ, §5.5) is materialized."""
        start_first, _ = _month_bounds(load_month)
        scenario = self._active_budget(load_month.year)
        end_year = (
            scenario.budget_year if scenario is not None else load_month.year
        )
        end_last = date(end_year, 12, 31)

        plans = crud.get_salary_plans(self.db, collab.id_collaborator)
        if plans:
            earliest_first, _ = _month_bounds(
                min(p.valid_from for p in plans)
            )
            if earliest_first > start_first:
                start_first = earliest_first
            else:
                # A plan opened earlier than the load month (e.g. alta
                # with hire_date in January imported in September) must
                # still be caused: the window goes back to that month,
                # never before 01/01 of the window year.
                start_first = max(earliest_first, date(end_year, 1, 1))
        return start_first, end_last


def materialize_for_scenario_year(db: Session, year: int) -> dict:
    """BE-S11 ENMIENDA (Opcion C): materializar la nomina de TODOS los
    colaboradores activos dentro del escenario recien activado de `year`.

    Llamado DESPUES del commit de set-target (la activacion es propia y
    sobrevive): ventana resolve_window(c, 01-01 del ano) => enero..31/12,
    con el mismo reemplazo idempotente R-13 por mes (no duplica, no toca
    lineas manuales). Nunca lanza: devuelve el resumen y los warnings;
    una nomina sin parametros (R-05) NO puede tumbar la designacion de
    la meta. Commit propio (T-05 del hook)."""
    out = {"lines_created": 0, "months_processed": 0, "collaborators": 0,
           "warnings": []}
    collabs = crud.list_active_collaborators(db)
    out["collaborators"] = len(collabs)
    if not collabs:
        return out
    engine = LaborCostEngine(db)
    anchor = date(year, 1, 1)
    try:
        for collab in collabs:
            start_first, end_last = engine.resolve_window(collab, anchor)
            run = engine.run_projection(collab, start_first, end_last)
            out["lines_created"] += run.created_lines
            out["months_processed"] += run.months_processed
            out["warnings"].extend(run.warnings)
        db.commit()
    except (MissingLaborParametersError, CostCatalogIncompleteError) as exc:
        db.rollback()
        out["warnings"].append(str(exc))
    except Exception as exc:  # la designacion de meta ya comiteo: el
        db.rollback()        # payroll hook degrada a warning, nunca a 500
        out["warnings"].append(
            "payroll materialization failed: %s" % (exc,)
        )
    return out
