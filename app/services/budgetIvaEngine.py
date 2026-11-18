"""
Budget IVA Engine - Events & Settlement Derivation (BE-S10-IVA)

Spec backend.02_20 §4: pure READ-ONLY aggregation layer (NFR-BE10-1, the
BR-19/BR-32/BR-CO-04 pattern of budgetEngine) — ZERO add/flush/commit/
delete anywhere: no quota, event or liquidation is ever materialized.
The only persisted IVA data in the system are the ``iva_periods``
calendar rows and the ``budget_lines.has_iva`` flag (D-S10-4); the
settlement is recomputed LIVE on every read.

T = TAX_RATE (app/core/constants.py) is the single rate source
(D-S10-1: no per-category or per-line rates in v1, PQ-S10-7). The basis
is ACCRUAL / causación (overrides D-S10-9): every event falls in the period
covering the line's budget_date —

    E1 ventas           INCOME, always taxed, flag IGNORED (D-S10-5),
                        budget_date
    E2 fixed_expenses   EXPENSE fixed, effective flag True (NULL ≡ True,
                        D-S10-3; False emits NOTHING, not a 0 event),
                        budget_date
    E3 variable_expenses EXPENSE variable_sales: rate × I_c(m) where
                        I_c(m) = income_ceco_by_month[c][m], the
                        budgeted income of the line's RESOLVED CECO c
                        (own CECO first, else the single billing CECO of
                        its (id_zone, id_line) bucket — Enmienda A-01 §10)
                        for the month of budget_date — base per CECO
                        (Spec 02_24 §6.2, BR-VE-07), anchored on the
                        line's budget_date (R-S10-4)
    E4 idem variable_receivables: rate × R_c(m) of the line's RESOLVED
                        CECO — base B2c parity per CECO. Enmienda A-02
                        (§11): R_c(m) = collections of the resolved CECO
                        (income entries by COBRO month, cfMonth
                        payment_date || budget_date, year of the CASH
                        month); the AR term left the base (no CECO in
                        accounts_receivable)
    E3bis variable_outflows: backend.02_28 (BR-VS-04) — NO event is
                        emitted. The "Variable por Salidas" behavior is
                        NOT deductible: its own base already includes the
                        tax payments (BR-VS-01), so a deduction would be
                        circular, and the identity of spec §2 must hold
                        to the cent without iteration. The branch is
                        EXPLICIT (continue) before the fixed `else`
                        below, which would otherwise emit an incorrect
                        E2 for this (and any unknown) behavior value.
    E5 import_vat       PURCHASE: T × costo_prov, costo_prov =
                        Total / (1 + %int) (§4.3, D-S10-6), cash event
                        on the import date budget_date
    E6 nationalization_vat PURCHASE: T × each internment installment
                        costo_int × payment_pct paid JUNTO con la cuota
                        (D-S10-7): date = budget_date + payment_days,
                        or ONE 100 % installment on the anchor when the
                        Line has a rate but no terms (BR-INT-04 mirror
                        of 02_19 §4); emitted ONLY under the same
                        `pct > 0 AND costo_int > 0` guards as the
                        carryover stream (02_19 §10.2 note).

%int irresoluble (CECO sin Línea o Línea sin fila en
line_internment_rates) ⇒ pct = 0 ⇒ E5 = T × Total and ZERO E6
(D-S10-8, Q4 opción 1 — no blocking warning). The E5/E6 formulas are a
faithful replica of the 02_19 §4 split in crud/budget/planning.py.

v1 is the PROJECTED settlement over the scenario's own lines: carryover
rows and the N−1 supplier/internment payment streams NEVER emit events
(D-S10-12, PQ-S10-2), and budgetEngine/project_cash_flow stay untouched
(R-S10-3).

Query economy (NFR-BE10-2): settlement()/events() pay Q1..Q7 of §4.1 —
7 constant round trips regardless of line count (Q5/Q6 skipped when no
purchase resolves to a Line, NFR-BE9-2 precedent). Raw floats run the
recurrence; round(2) happens ONLY on the response (NFR-BE10-4). Event
order (date, concept, id_budget_line ASC), period order period_no ASC.

Response contract: §4.6 verbatim (IvaSettlementResult), including the
LITERAL 'deductable' totals key and the literal no-calendar warning
'No IVA calendar for {year}; configure /budget/iva-period' (AC-BE10-6).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.core.constants import TAX_RATE
from app.services.cecoBucketUtils import (
    build_ceco_buckets,
    load_ceco_bucket_catalog,
    resolve_income_ceco,
)
from app.models.budget import (
    AccountReceivable as AccountReceivableModel,
    Budget as BudgetModel,
    BudgetLine as BudgetLineModel,
    CostCenter as CostCenterModel,
    IvaPeriod as IvaPeriodModel,
    LineInternmentRate as LineInternmentRateModel,
    LineInternmentTerm as LineInternmentTermModel,
)

# §4.5 concept keys — LITERAL fields of the §4.6 response contract. The
# generated side has exactly ONE concept (ventas): every sale is taxed
# and the line flag is ignored (D-S10-5, PQ-S10-1 reserved).
CONCEPT_VENTAS = "ventas"
CONCEPT_FIXED_EXPENSES = "fixed_expenses"        # E2
CONCEPT_VARIABLE_EXPENSES = "variable_expenses"  # E3 + E4
CONCEPT_IMPORT_VAT = "import_vat"                # E5
CONCEPT_NATIONALIZATION_VAT = "nationalization_vat"  # E6
DEDUCTIBLE_CONCEPTS = (
    CONCEPT_FIXED_EXPENSES,
    CONCEPT_VARIABLE_EXPENSES,
    CONCEPT_IMPORT_VAT,
    CONCEPT_NATIONALIZATION_VAT,
)

# §4.4 LITERAL warning (AC-BE10-6 quotes it; the FE matches it verbatim).
NO_CALENDAR_WARNING = "No IVA calendar for {year}; configure /budget/iva-period"


def _enum_value(value: Any) -> str:
    """Lowercase VALUE of an enum-backed column, storage-agnostic: the
    ORM hands back members (LineTypeEnum.INCOME / BehaviorTypeEnum.FIXED
    — budget_lines.line_type is a PG enum storing the NAMES while
    behavior_type is the legacy varchar, cf. get_carryover_lines) and a
    str-enum member's .value is the lowercase token the §4 rules key on.
    Plain strings are lowercased too, so nothing can mis-branch."""
    return str(getattr(value, "value", value)).lower()


class BudgetIvaEngine:
    """Projected IVA events + calendar settlement of ONE budget scenario
    (spec backend.02_20 §4). Pure read layer: the caller's Session is
    used for SELECTs only (NFR-BE10-1)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # Facts (Q1..Q7 of §4.1)
    # ──────────────────────────────────────────────

    def _facts(
        self, id_budget: int, year: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """Gather the seven facts of §4.1 for the derivation. Returns
        None ONLY when the budget is missing (Q1 — the endpoint answers
        the 404, spec §5.9)."""
        # Q1 — the scenario itself (year defaults to budget.budget_year,
        # §5.9; a ?year= override liquidates the SAME lines under another
        # calendar and re-routes movements of the other years to
        # out_of_year_events, §4.4).
        budget = self.db.query(BudgetModel).filter(
            BudgetModel.id_budget == id_budget
        ).first()
        if budget is None:
            return None
        if year is None:
            year = budget.budget_year

        # Q2 — budget_lines of the scenario, ONE scan, deterministic id
        # order, with the CECO's id_line resolved by LEFT JOIN (purchases
        # need it for the §4 split; a missing CECO row — impossible under
        # the NOT NULL FK — simply degrades to pct = 0, D-S10-8).
        line_rows = (
            self.db.query(BudgetLineModel, CostCenterModel.id_line)
            .outerjoin(
                CostCenterModel,
                BudgetLineModel.id_cost_center
                == CostCenterModel.id_cost_center,
            )
            .filter(BudgetLineModel.id_budget == id_budget)
            .order_by(BudgetLineModel.id_budget_line.asc())
            .all()
        )

        # Q3 — income_budget_by_month MIRROR (02_02 §6 base B1, spec
        # §4.1 "ingresos del propio escenario"): budgeted income summed
        # by ACCRUAL month (month of budget_date), computed from the Q2
        # scan itself (zero extra SQL) exactly like project_cash_flow's
        # income_rows loop, so the E3/E4 bases are parity figures.
        # Spec 02_24 §6.2 / BR-VE-07: additionally the per-CECO mirror
        # income_ceco_by_month[c][m] = I_c(m), the SAME base scope B1c
        # as the cash-flow engine (global dict kept for other uses).
        income_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}
        income_ceco_by_month: Dict[int, Dict[int, float]] = {}
        # Enmienda A-02 (spec backend.02_24 §11): the E4 mirror of
        # COLLECTIONS, same dict pass as the income mirror — income lines
        # positioned by their PAYMENT month (cfMonth = payment_date ||
        # budget_date, same convention as the Flujo view) and filtered by
        # the YEAR OF THAT CASH DATE (lines collected outside the
        # settlement year land on the view's out-of-year buckets, so they
        # neither fatten an in-year month nor are smugged into their
        # budget month). NET amounts (sin IVA gross-up, §11.3).
        cash_received_ceco_by_month: Dict[int, Dict[int, float]] = {}
        purchase_lines: Set[int] = set()
        for line, id_line in line_rows:
            lt = _enum_value(line.line_type)
            if lt == "income" and line.budget_date is not None:
                income_by_month[line.budget_date.month] += float(
                    line.projected_amount or 0.0
                )
                if line.id_cost_center is not None:
                    income_ceco_map = income_ceco_by_month.setdefault(
                        int(line.id_cost_center),
                        {m: 0.0 for m in range(1, 13)},
                    )
                    income_ceco_map[line.budget_date.month] += float(
                        line.projected_amount or 0.0
                    )
                    cash_date = line.payment_date or line.budget_date
                    if cash_date.year == year:
                        cash_ceco_map = cash_received_ceco_by_month.setdefault(
                            int(line.id_cost_center),
                            {m: 0.0 for m in range(1, 13)},
                        )
                        cash_ceco_map[cash_date.month] += float(
                            line.projected_amount or 0.0
                        )
            elif lt == "purchase" and id_line is not None:
                purchase_lines.add(id_line)

        # Q4 — the AR half of the legacy net_income_by_month (02_02 §6
        # base B2): accounts_receivable.balance by month of due_date OF
        # THE SETTLEMENT YEAR, same unfiltered-by-budget scope as the
        # legacy query (parity of cifras, AC-BE10-7 E4 case).
        # NOTE (Enmienda A-01, 2026-10-20): accounts_receivable has NO
        # cost-center dimension in the schema (model, table and the
        # EstadoCuenta306090 template agree), so a per-CECO AR mirror is
        # IMPOSSIBLE — the previous attempt to group AR by
        # id_cost_center crashed with AttributeError on every real run.
        # The AR overdue term keeps feeding the GLOBAL recaudo figures;
        # the per-CECO E4 term is 0 today (BR-VE-06 conservative zero
        # rule) until the AR upload gains a CECO.
        ar_by_month: Dict[int, float] = {m: 0.0 for m in range(1, 13)}
        ar_rows = (
            self.db.query(
                extract("month", AccountReceivableModel.due_date).label("month"),
                func.coalesce(func.sum(AccountReceivableModel.balance), 0),
            )
            .filter(
                extract("year", AccountReceivableModel.due_date) == year,
            )
            .group_by("month")
            .all()
        )
        for row in ar_rows:
            ar_by_month[int(row.month)] += float(row[1])

        # Enmienda A-01 (spec backend.02_24 §10, AC-BE24-11): the E3/E4
        # bases resolve through the SAME helper as the cash-flow engine's
        # B1/B2 — own CECO first, else the SINGLE billing CECO of the
        # line's (id_zone, id_line) bucket, else None ⇒ 0. The catalog is
        # one query; the buckets are derived from the income mirror by
        # dict passes (no new JOINs, no N+1). The collections mirror of
        # Enmienda A-02 (§11) shares the resolver: the RESOLVED CECO is
        # looked up in the COBRO mirror, never in AR (removed from the
        # base per §11 — the AR schema has no CECO; BR-VE-06 zero rule).
        ceco_catalog = load_ceco_bucket_catalog(self.db)
        income_bucket_by_month, income_bucket_cecos = build_ceco_buckets(
            income_ceco_by_month, ceco_catalog)

        # Q5/Q6 — split catalogs IN over the DISTINCT purchase Lines
        # (BE-S9 §5.4 economy mirror): rates {id_line: pct} and the
        # internment terms grouped in the D-7 order. BOTH queries are
        # skipped entirely when no purchase resolves to a Line (every pct
        # is then 0, D-S10-8, and the §4 derivation needs nothing).
        rates: Dict[int, float] = {}
        int_terms_by_line: Dict[int, List[Any]] = {}
        sorted_lines = sorted(purchase_lines)
        if sorted_lines:
            rates = {
                rate.id_line: float(rate.internment_pct)
                for rate in self.db.query(LineInternmentRateModel).filter(
                    LineInternmentRateModel.id_line.in_(sorted_lines)
                ).order_by(
                    LineInternmentRateModel.id_line,
                ).all()
            }
            int_terms_by_line = {id_line: [] for id_line in sorted_lines}
            for term in (
                self.db.query(LineInternmentTermModel)
                .filter(LineInternmentTermModel.id_line.in_(sorted_lines))
                .order_by(
                    LineInternmentTermModel.id_line,
                    LineInternmentTermModel.payment_days,
                    LineInternmentTermModel.id_line_internment_term,
                )
                .all()
            ):
                int_terms_by_line[term.id_line].append(term)

        # Q7 — calendar of the year in period_no ASC (the §4.4
        # first-cover order). Absence is legal: periods: [] + literal
        # warning + everything unassigned (never an error, §4.4).
        periods = (
            self.db.query(IvaPeriodModel)
            .filter(IvaPeriodModel.period_year == year)
            .order_by(IvaPeriodModel.period_no.asc())
            .all()
        )

        events, out_of_year = self._derive_events(
            line_rows, income_ceco_by_month, rates,
            int_terms_by_line, year, ceco_catalog, income_bucket_cecos,
            cash_received_ceco_by_month,
        )
        return {
            "budget": budget,
            "year": year,
            "periods": periods,
            "events": events,
            "out_of_year": out_of_year,
        }

    # ──────────────────────────────────────────────
    # Event derivation (E1..E6 of §4.2/§4.3)
    # ──────────────────────────────────────────────

    def _derive_events(
        self,
        line_rows: List[Tuple[Any, Optional[int]]],
        income_ceco_by_month: Dict[int, Dict[int, float]],
        rates: Dict[int, float],
        int_terms_by_line: Dict[int, List[Any]],
        year: int,
        ceco_catalog: Optional[Dict[int, tuple]] = None,
        income_bucket_cecos: Optional[Dict[tuple, set]] = None,
        cash_received_ceco_by_month: Optional[Dict[int, Dict[int, float]]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Build the raw IVA events (amounts as RAW floats = base × T,
        zero intermediate rounding per NFR-BE10-4) and count the events
        whose movement date falls OUTSIDE the settlement year (§4.4:
        ``meta.out_of_year_events`` and excluded — the calendar only
        ever covers its own year, so the filter precedes the assignment).

        Spec 02_24 §6.2 (BR-VE-07) + Enmienda A-01 (§10, AC-BE24-11):
        the E3/E4 bases come from the per-CECO mirrors resolved through
        resolve_income_ceco — the same priority (own CECO, then the
        single billing CECO of the (zone, line) bucket) and the same
        helpers as the cash-flow engine's B1/B2 (02_24 §6.1 / §10.2).

        Flag semantics (§4.3): an EXPENSE with has_iva False emits
        NOTHING (no 0-event); NULL/True emits (D-S10-3). INCOME always
        emits E1 and PURCHASE always emits E5 (+E6 under the guards) —
        their stored flags are ignored (D-S10-5 / §3.1)."""
        T = TAX_RATE
        events: List[Dict[str, Any]] = []
        out_of_year = 0

        def emit(
            event_date: Any,
            concept: str,
            id_budget_line: int,
            side: str,
            amount: float,
        ) -> None:
            nonlocal out_of_year
            if event_date is None:
                # Defensive only: budget_date is NOT NULL, and every
                # fallback resolves to it. Such a line emits nothing.
                return
            if event_date.year != year:
                out_of_year += 1
                return
            events.append({
                "date": event_date,
                "concept": concept,
                "side": side,
                "id_budget_line": id_budget_line,
                "amount": amount,
            })

        for line, id_line in line_rows:
            line_type = _enum_value(line.line_type)
            amount = float(line.projected_amount or 0.0)
            lid = line.id_budget_line

            if line_type == "income":
                # E1 (§4.2) — recaudo sobre el NETO proyectado; el flag
                # de una INCOME se IGNORA (D-S10-5, AC-BE10-2).
                emit(line.budget_date,
                     CONCEPT_VENTAS, lid, "generated", amount * T)

            elif line_type == "expense":
                # D-S10-3: NULL ≡ True is the ONLY flag rule; explicit
                # False opts the line out (§4.3 "no se emite 0").
                if line.has_iva is False:
                    continue
                behavior = _enum_value(line.behavior_type)
                if behavior == "variable_sales":
                    # E3 (Spec 02_24 §6.2, BR-VE-01/02/07 + Enmienda A-01
                    # §10) — base B1c per CECO RESOLVED: own CECO if it
                    # has income, else the single billing CECO of the
                    # line's (id_zone, id_line) bucket; the base month is
                    # the line's ACCRUAL month (budget_date,
                    # cash-approximated there per R-S10-4). An unresolvable
                    # CECO (0/multiple generators, NULL zone/line) or a
                    # missing base simply contributes 0 (BR-VE-02).
                    if line.budget_date is not None:
                        rate = float(line.variable_rate or 0.0)
                        m = line.budget_date.month
                        c = resolve_income_ceco(
                            line.id_cost_center,
                            income_ceco_by_month,
                            income_bucket_cecos or {},
                            ceco_catalog or {},
                        )
                        income_ceco_map = (
                            income_ceco_by_month.get(c)
                            if c is not None else None
                        )
                        base = rate * (
                            income_ceco_map.get(m, 0.0)
                            if income_ceco_map else 0.0
                        )
                        emit(line.budget_date, CONCEPT_VARIABLE_EXPENSES,
                             lid, "deductible", base * T)
                elif behavior == "variable_receivables":
                    # E4 (Spec 02_24 §6.2, BR-VE-04/07 + Enmienda A-02
                    # §11) — base B2c of the RESOLVED CECO (same helper
                    # as E3/B1/B2): the COLLECTIONS of the CECO the
                    # resolution points to (income entries by COBRO
                    # month = payment_date || budget_date, Enmienda
                    # A-02). The AR term LEFT the base per §11: the
                    # budget's recaudo is built from the plan's own
                    # ENTRADAS, which DO carry a CECO; the AR of
                    # accounts_receivable has no CECO dimension
                    # (BR-VE-06 zero rule, now a structural condition of
                    # the base instead of a conservative 0 term).
                    # Accrual stays on the line's budget_date month; the
                    # base month m is that same month. Unresolvable /
                    # missing entries degrade to 0 (no exclusion,
                    # BR-VE-02).
                    if line.budget_date is not None:
                        rate = float(line.variable_rate or 0.0)
                        m = line.budget_date.month
                        c = resolve_income_ceco(
                            line.id_cost_center,
                            income_ceco_by_month,
                            income_bucket_cecos or {},
                            ceco_catalog or {},
                        )
                        cash_ceco_map = (
                            cash_received_ceco_by_month.get(c)
                            if c is not None
                            and cash_received_ceco_by_month is not None
                            else None
                        )
                        base = rate * (
                            cash_ceco_map.get(m, 0.0)
                            if cash_ceco_map else 0.0
                        )
                        emit(line.budget_date, CONCEPT_VARIABLE_EXPENSES,
                             lid, "deductible", base * T)
                elif behavior == "variable_outflows":
                    # backend.02_28 (BR-VS-04): NOT deductible — the line
                    # emits NO IVA-settlement events (E1..E6). The
                    # variable_outflows base already includes the tax
                    # payments, so a deduction would create circularity;
                    # the branch is EXPLICIT before the fixed `else`
                    # below, which would otherwise emit an incorrect E2
                    # for this behavior value.
                    continue
                else:
                    # E2 — fixed (also the safety branch for any dirty
                    # behavior value: never invent a variable base).
                    emit(line.budget_date,
                         CONCEPT_FIXED_EXPENSES, lid, "deductible",
                         amount * T)

            elif line_type == "purchase":
                # E5/E6 — §4.3 with the 02_19 §4 formulas replicated:
                # costo_prov = Total / (1 + pct); costo_int = Total −
                # costo_prov (BR-INT-01). pct irresoluble => 0 => E5 =
                # T × Total on the anchor and ZERO E6 (D-S10-8). The
                # has_iva flag NEVER applies here (§3.1).
                pct = rates.get(id_line, 0.0) if id_line is not None else 0.0
                costo_prov = amount / (1.0 + pct)
                costo_int = amount - costo_prov
                emit(line.budget_date, CONCEPT_IMPORT_VAT, lid,
                     "deductible", costo_prov * T)
                # Same guards as the carryover internment stream:
                # pct > 0 AND costo_int > 0 (02_19 §10.2 note).
                if pct > 0 and costo_int > 0:
                    terms = (
                        int_terms_by_line.get(id_line)
                        if id_line is not None else None
                    )
                    if terms:
                        # Causation basis: the nationalization VAT belongs to
                        # the import date, whatever the installment schedule.
                        for term in terms:  # D-7 order from Q6
                            emit(
                                line.budget_date,
                                CONCEPT_NATIONALIZATION_VAT, lid,
                                "deductible",
                                costo_int * float(term.payment_pct) * T,
                            )
                    else:
                        # BR-INT-04 mirror: rate but no terms -> ONE
                        # 100 % installment on the import date.
                        emit(line.budget_date,
                             CONCEPT_NATIONALIZATION_VAT, lid,
                             "deductible", costo_int * T)

        # NFR-BE10-4 — deterministic order (date, concept, id ASC).
        events.sort(key=lambda e: (e["date"], e["concept"],
                                   e["id_budget_line"]))
        return events, out_of_year

    # ──────────────────────────────────────────────
    # Public surface (both READ-ONLY)
    # ──────────────────────────────────────────────

    def events(
        self, id_budget: int, year: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """The in-year event register of the scenario in the §4.3/§4.4
        deterministic order (dates ISO, amounts round(2) at the exit —
        the raw floats never leave this layer). None when the budget is
        missing. Exposed for parity checks (the settlement bucketing is
        a pure function of this list); NOT part of the HTTP contract."""
        facts = self._facts(id_budget, year)
        if facts is None:
            return None
        return [{
            "date": e["date"].isoformat(),
            "concept": e["concept"],
            "side": e["side"],
            "id_budget_line": e["id_budget_line"],
            "amount": round(e["amount"], 2),
        } for e in facts["events"]]

    def settlement(
        self, id_budget: int, year: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """§4.6 contract: per-period buckets (first-cover, §4.4), the
        unlimited-carryover recurrence (§4.5, raw floats inside, round(2)
        out), the separate unassigned sums, the out-of-year count and
        the column totals. Returns None ONLY when the budget is missing
        (the endpoint answers the 404 with the §5.9 literal)."""
        facts = self._facts(id_budget, year)
        if facts is None:
            return None
        budget: Any = facts["budget"]
        year = facts["year"]
        periods: List[Any] = facts["periods"]
        events: List[Dict[str, Any]] = facts["events"]

        warnings: List[str] = []
        if not periods:
            # AC-BE10-6: no calendar is NEVER an error — 200 with
            # periods: [] and everything in unassigned, warning literal.
            warnings.append(NO_CALENDAR_WARNING.format(year=year))

        # §4.4 assignment — FIRST period (period_no ASC) covering the
        # movement date; gaps and the no-calendar case land in
        # unassigned; overlaps degrade to the lower period_no
        # deterministically.
        buckets: Dict[int, List[Dict[str, Any]]] = {
            p.id_iva_period: [] for p in periods
        }
        unassigned: List[Dict[str, Any]] = []
        for event in events:
            covered = None
            for p in periods:
                if p.date_from <= event["date"] <= p.date_to:
                    covered = p
                    break
            if covered is None:
                unassigned.append(event)
            else:
                buckets[covered.id_iva_period].append(event)

        # §4.5 recurrence — saldo_favor_0 = 0, period_no ASC, RAW floats
        # chained (prior_balance feeds the next base unrounded), pago_p =
        # max(0, base) as the ONLY disbursement (A8), favor unlimited
        # (D-S10-11: no refund/compensation in v1, PQ-S10-6).
        rows: List[Dict[str, Any]] = []
        carry_raw = 0.0
        tot_generated = 0.0
        tot_deductible = 0.0
        tot_payments = 0.0
        for p in periods:
            evs = buckets[p.id_iva_period]
            g = sum(e["amount"] for e in evs if e["side"] == "generated")
            ded: Dict[str, float] = {c: 0.0 for c in DEDUCTIBLE_CONCEPTS}
            for e in evs:
                if e["side"] == "deductible":
                    ded[e["concept"]] += e["amount"]
            d = sum(ded.values())
            base_raw = g - d - carry_raw
            payment_raw = max(0.0, base_raw)
            next_carry_raw = max(0.0, -base_raw)
            rows.append({
                "period_no": p.period_no,
                "date_from": p.date_from.isoformat(),
                "date_to": p.date_to.isoformat(),
                "payment_due_date": p.payment_due_date.isoformat(),
                "description": p.description,
                "generated": {CONCEPT_VENTAS: round(g, 2)},
                "deductible": {c: round(ded[c], 2)
                               for c in DEDUCTIBLE_CONCEPTS},
                "prior_balance": round(carry_raw, 2),
                "tax_base": round(base_raw, 2),
                "payment": round(payment_raw, 2),
                "carry_balance": round(next_carry_raw, 2),
                "events_count": len(evs),
            })
            tot_generated += g
            tot_deductible += d
            tot_payments += payment_raw
            carry_raw = next_carry_raw

        un_generated = sum(e["amount"] for e in unassigned
                           if e["side"] == "generated")
        un_deductible = sum(e["amount"] for e in unassigned
                            if e["side"] == "deductible")

        # §4.6 — totals are the PERIOD column sums only: unassigned
        # reports its own separate sums and never participates in the
        # recurrence (§4.4), out-of-year events are already excluded.
        return {
            "id_budget": budget.id_budget,
            "budget_name": budget.budget_name,
            "year": year,
            "tax_rate_used": TAX_RATE,
            "basis": "accrual",
            "periods": rows,
            "unassigned": {
                "generated": round(un_generated, 2),
                "deductible": round(un_deductible, 2),
                "events_count": len(unassigned),
            },
            "totals": {
                "generated": round(tot_generated, 2),
                # LITERAL §4.6 (stakeholder spelling with the "t") — do
                # not "fix" it: it is quoted wire contract (AC-BE10-4).
                "deductable": round(tot_deductible, 2),
                "payments": round(tot_payments, 2),
                "final_balance": round(carry_raw, 2),
            },
            "meta": {
                "warnings": warnings,
                "out_of_year_events": facts["out_of_year"],
                "filters": {"id_budget": id_budget, "year": year},
            },
        }
