"""Decimal tax projection engine. Rates and dates always come from catalogs.

The SIMPLE calculation is deliberately period based.  A rate is selected for
each calendar period using that period's gross income; the annual total must
never be used to select a SIMPLE bracket.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.budget import Budget, BudgetLine
from app.services.budgetIvaEngine import BudgetIvaEngine


# Importing app.crud eagerly makes a direct import of this service participate
# in the legacy app.api <-> app.core.auth cycle.  Keep these small delegates
# lazy while retaining patchable names for unit tests and the existing CRUD
# registration pattern.
def list_tax_rates(*args, **kwargs):
    from app.crud.budget.taxPlanning import list_tax_rates as operation
    return operation(*args, **kwargs)


def list_tax_calendar(*args, **kwargs):
    from app.crud.budget.taxPlanning import list_tax_calendar as operation
    return operation(*args, **kwargs)


def add_budget_tax_result(*args, **kwargs):
    from app.crud.budget.taxPlanning import add_budget_tax_result as operation
    return operation(*args, **kwargs)


def clear_budget_tax_results(*args, **kwargs):
    from app.crud.budget.taxPlanning import clear_budget_tax_results as operation
    return operation(*args, **kwargs)

ZERO = Decimal("0")
Q = Decimal("0.01")

# Colombian tax planning classification used consistently by the P&L and cash
# flow projections.  Retentions are credits/saldos unless an accounting rule
# explicitly reclassifies them; they must not silently inflate expenses.
P_AND_L_TAX_TYPES = frozenset(("income_ordinary", "simple", "ica"))
CASH_CREDIT_TAX_TYPES = frozenset(("reteiva", "withholding", "reteica"))
# IVA of the purchase side (import and nationalization) is the ReteIVA base.
PURCHASE_IVA_CONCEPTS = frozenset(("import_vat", "nationalization_vat"))


def D(v):
    """Convert DB/JSON numeric values without going through ``float``."""
    return Decimal(str(v or 0))


def money(v):
    return D(v).quantize(Q, rounding=ROUND_HALF_UP)


def rate_decimal(value):
    """Keep the configured percentage precision in the result.

    ``money`` is only for COP amounts.  Applying it to a rate such as 0.035
    would turn it into 0.04 and consequently change the tax calculation.
    """
    return D(value)


def _line_type(line):
    return str(getattr(line, "line_type", "").value
               if hasattr(getattr(line, "line_type", None), "value")
               else getattr(line, "line_type", "")).lower()


def _month_from_key(key: Any, year: int) -> Optional[int]:
    """Return the month represented by a monthly override key.

    The API historically accepted a free-form JSON object.  Support the
    formats already used by clients (``YYYY-MM``, ISO dates and ``1``..``12``)
    without changing that contract.
    """
    text = str(key).strip().lower()
    if text.isdigit() and 1 <= int(text) <= 12:
        return int(text)
    # "YYYY-MM" (optionally followed by a day): the year must be the budget year.
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?", text)
    if match:
        month = int(match.group(2))
        if int(match.group(1)) == year and 1 <= month <= 12:
            return month
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
    return parsed.month if parsed.year == year else None


def _period_sequence(period, fallback: int) -> int:
    return int(getattr(period, "sequence", None) or fallback)


def _value(row: Any, name: str, default=ZERO):
    """Read a value from either an ORM result or a calculation dictionary."""
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def tax_pnl_date(row: Any, budget_year: Optional[int] = None) -> Optional[date]:
    """Return the date on which a tax result belongs in the budget P&L.

    Tax periods and cash dates are deliberately different dimensions.  SIMPLE
    and ordinary income tax are annual P&L charges and are presented in
    December of the budget year, even when ordinary tax is paid in the next
    year.  ICA is presented when it is liquidated/declared.  Retentions and
    reteIVA/reteICA are credits/saldos, not P&L expenses, so they have no P&L
    date (their payment date remains available to the cash-flow dimension).

    ``calculation_trace`` is used as a snapshot-friendly source.  The fallback
    logic keeps results calculated before this field was introduced readable.
    """
    typ = str(_value(row, "tax_type", "")).lower()
    trace = _value(row, "calculation_trace", {}) or {}
    if isinstance(trace, dict):
        year = trace.get("pnl_year")
        month = trace.get("pnl_month")
        if year is not None and month is not None:
            try:
                return date(int(year), int(month), 1)
            except (TypeError, ValueError):
                pass

    if typ in ("income_ordinary", "simple"):
        year = budget_year
        if year is None:
            period_end = _value(row, "period_end")
            year = period_end.year if period_end is not None else None
        return date(int(year), 12, 1) if year is not None else None

    if typ == "ica":
        declaration = _value(row, "declaration_date")
        return declaration.replace(day=1) if declaration is not None else (
            _value(row, "period_end").replace(day=1)
            if _value(row, "period_end") is not None else None
        )
    return None


def tax_result_locations(row: Any, budget_year: Optional[int] = None) -> Dict[str, Any]:
    """Expose both accounting and cash coordinates for a tax snapshot."""
    pnl_date = tax_pnl_date(row, budget_year)
    payment_date = _value(row, "payment_date")
    payment_year = payment_date.year if payment_date is not None else _value(
        row, "payment_year"
    )
    return {
        "pnl_month": pnl_date.month if pnl_date is not None else None,
        "pnl_year": pnl_date.year if pnl_date is not None else None,
        "payment_date": payment_date,
        "payment_year": int(payment_year) if payment_year is not None else None,
    }


def tax_cash_advance(row: Any) -> Decimal:
    """Return an advance actually paid in the projected period.

    ``advance_amount`` is the credit applied to a result and can include
    ``prior_advances``.  SIMPLE stores the current in-year advance in its
    calculation trace, so using the raw aggregate field would double count a
    prior credit in the budget cash flow.
    """
    trace = _value(row, "calculation_trace", {}) or {}
    if isinstance(trace, dict) and "cash_advance" in trace:
        return money(trace["cash_advance"])
    return money(_value(row, "advance_amount", ZERO))


def tax_cash_advance_date(row: Any) -> Optional[date]:
    """Date on which an advance is paid; None means "use the payment date"."""
    trace = _value(row, "calculation_trace", {}) or {}
    if isinstance(trace, dict) and trace.get("advance_cash_date"):
        try:
            return date.fromisoformat(str(trace["advance_cash_date"])[:10])
        except ValueError:
            return None
    return None


def aggregate_tax_cash_flow(rows: Iterable[Any]) -> Dict[str, Any]:
    """Aggregate every persisted tax result by its payment month/year.

    A tax result is a snapshot, so this function intentionally does not filter
    by tax type.  ``payments`` is the post-credit ``balance_payable`` and
    ``net_outflow`` is cash advances plus payments.  Withholdings are returned
    as a separate credit for reconciliation, never added to the cash outflow.
    """
    buckets: Dict[Tuple[Optional[int], Optional[int]], Dict[str, Any]] = {}
    type_buckets: Dict[Tuple[Tuple[Optional[int], Optional[int]], str], Dict[str, Decimal]] = {}
    warnings: List[str] = []

    def amount(row, field):
        return money(_value(row, field, ZERO))

    def bucket_for(key):
        if key not in buckets:
            year, month = key
            label = f"{year:04d}-{month:02d}" if year and month else (
                f"{year:04d}-undated" if year else "undated"
            )
            buckets[key] = {
                "period": label,
                "payment_year": year,
                "payment_month": month,
                "tax_caused": ZERO,
                "advance_amount": ZERO,
                "withholding_amount": ZERO,
                "payments": ZERO,
                "net_outflow": ZERO,
                "by_type": [],
            }
        return buckets[key]

    def typed_for(key, typ):
        return type_buckets.setdefault((key, typ), {
            "tax_type": typ,
            "tax_caused": ZERO,
            "advance_amount": ZERO,
            "withholding_amount": ZERO,
            "payments": ZERO,
            "net_outflow": ZERO,
        })

    for row in rows:
        payment_date = _value(row, "payment_date")
        payment_year = _value(row, "payment_year")
        if payment_date is not None:
            payment_year = payment_date.year
            payment_month = payment_date.month
        else:
            payment_month = None
            if payment_year is None:
                warnings.append(
                    f"Tax result {_value(row, 'id_budget_tax_result', '?')} has no payment date"
                )
        key = (int(payment_year) if payment_year is not None else None, payment_month)
        typ = str(_value(row, "tax_type", "unknown"))

        # Caused tax, withholdings and the balance are cash/accounting facts of
        # the payment date.  Advances are cash on their own date (ordinary tax:
        # December of the fiscal year), so they are placed separately below.
        payments = amount(row, "balance_payable")
        for target in (bucket_for(key), typed_for(key, typ)):
            target["tax_caused"] += amount(row, "tax_caused")
            target["withholding_amount"] += amount(row, "withholding_amount")
            target["payments"] += payments
            target["net_outflow"] += payments

        cash_advance = tax_cash_advance(row)
        if cash_advance:
            advance_date = tax_cash_advance_date(row)
            advance_key = (
                (advance_date.year, advance_date.month) if advance_date is not None else key
            )
            for target in (bucket_for(advance_key), typed_for(advance_key, typ)):
                target["advance_amount"] += cash_advance
                target["net_outflow"] += cash_advance

    for key, bucket in buckets.items():
        bucket["by_type"] = [
            type_buckets[(key, typ)] for _key, typ in sorted(
                (k for k in type_buckets if k[0] == key), key=lambda item: item[1]
            )
        ]
        for field in ("tax_caused", "advance_amount", "withholding_amount", "payments", "net_outflow"):
            bucket[field] = money(bucket[field])
        bucket["advances"] = bucket["advance_amount"]
        bucket["withholdings"] = bucket["withholding_amount"]
        bucket["cash_outflow"] = bucket["net_outflow"]
        for typed in bucket["by_type"]:
            for field in ("tax_caused", "advance_amount", "withholding_amount", "payments", "net_outflow"):
                typed[field] = money(typed[field])

    ordered = [buckets[key] for key in sorted(
        buckets, key=lambda item: (item[0] is None, item[0] or 0, item[1] is None, item[1] or 0)
    )]
    totals = {
        "period": "total",
        "payment_year": None,
        "payment_month": None,
        "tax_caused": money(sum((b["tax_caused"] for b in ordered), ZERO)),
        "advance_amount": money(sum((b["advance_amount"] for b in ordered), ZERO)),
        "withholding_amount": money(sum((b["withholding_amount"] for b in ordered), ZERO)),
        "payments": money(sum((b["payments"] for b in ordered), ZERO)),
        "net_outflow": money(sum((b["net_outflow"] for b in ordered), ZERO)),
        "advances": money(sum((b["advance_amount"] for b in ordered), ZERO)),
        "withholdings": money(sum((b["withholding_amount"] for b in ordered), ZERO)),
        "cash_outflow": money(sum((b["net_outflow"] for b in ordered), ZERO)),
        "by_type": [],
    }
    total_types: Dict[str, Dict[str, Decimal]] = {}
    for bucket in ordered:
        for typed in bucket["by_type"]:
            total = total_types.setdefault(typed["tax_type"], {
                "tax_type": typed["tax_type"], "tax_caused": ZERO,
                "advance_amount": ZERO, "withholding_amount": ZERO,
                "payments": ZERO, "net_outflow": ZERO,
            })
            for field in ("tax_caused", "advance_amount", "withholding_amount", "payments", "net_outflow"):
                total[field] += typed[field]
    for typed in total_types.values():
        for field in ("tax_caused", "advance_amount", "withholding_amount", "payments", "net_outflow"):
            typed[field] = money(typed[field])
    totals["by_type"] = [total_types[key] for key in sorted(total_types)]
    return {"monthly": ordered, "totals": totals, "warnings": sorted(set(warnings))}

class BudgetTaxEngine:
    def __init__(self, db: Session):
        self.db = db

    def _rate(self, rates, typ, profile, base, as_of: Optional[date] = None):
        """Resolve the most specific configured rate for a period base."""
        candidates = []
        for rate in rates:
            if rate.tax_type != typ or not rate.is_active:
                continue
            if rate.regime and rate.regime != profile.regime:
                continue
            if (rate.economic_activity_code
                    and rate.economic_activity_code != profile.economic_activity_code):
                continue
            if (rate.municipality_code
                    and rate.municipality_code != profile.main_municipality_code):
                continue
            if rate.income_min is not None and base < D(rate.income_min):
                continue
            if rate.income_max is not None and base > D(rate.income_max):
                continue
            if as_of is not None:
                if rate.valid_from is not None and as_of < rate.valid_from:
                    continue
                if rate.valid_to is not None and as_of > rate.valid_to:
                    continue
            candidates.append(rate)

        # Explicit activity/municipality/range definitions win over generic
        # defaults.  The final bounds make the choice deterministic when a
        # catalog contains overlapping ranges.
        return (sorted(
            candidates,
            key=lambda item: (
                item.economic_activity_code is not None,
                item.municipality_code is not None,
                item.income_min is not None,
                D(item.income_min) if item.income_min is not None else ZERO,
            ),
            reverse=True,
        )[0] if candidates else None)

    @staticmethod
    def _tax_amount(base, rate_obj):
        if rate_obj is None:
            return ZERO
        amount = base * rate_decimal(rate_obj.rate)
        # fixed_amount is part of the configurable rate catalog.  It is zero
        # for the usual SIMPLE percentage brackets, but must not be ignored
        # when a configured tariff uses it.  It is a charge on a positive base:
        # a period or scenario without base (e.g. no profit) owes nothing.
        if base > 0 and getattr(rate_obj, "fixed_amount", None) is not None:
            amount += D(rate_obj.fixed_amount)
        return max(ZERO, amount)

    @staticmethod
    def _active_periods(calendars: Iterable[Any], tax_type: str,
                        regime: Optional[str] = None) -> List[Any]:
        candidates = [c for c in calendars if c.tax_type == tax_type
                      and getattr(c, "is_active", True)]
        if regime is not None:
            # list_tax_calendar intentionally returns shared (NULL regime) and
            # regime-specific rows.  Prefer the specific row per period so a
            # normal SIMPLE catalog cannot accidentally become twelve periods.
            selected: Dict[Tuple[Any, Any], Any] = {}
            for period in candidates:
                # The same date range is one period, whatever its sequence number.
                key = (period.period_start, period.period_end)
                current = selected.get(key)
                if current is None or (
                        getattr(period, "regime", None) == regime
                        and getattr(current, "regime", None) != regime):
                    selected[key] = period
            candidates = list(selected.values())
        return sorted(
            candidates,
            key=lambda c: (_period_sequence(c, 0), c.period_start),
        )

    @staticmethod
    def _override_base(override: Dict[str, Any], period, sequence: int,
                       year: int) -> Tuple[Decimal, bool]:
        """Aggregate a monthly/bimonthly sales-base override for a period.

        Returns the base and whether the override contains data for the period.
        A missing period is reported to the caller instead of silently being 0.
        """
        total = ZERO
        matched = False
        for key, value in override.items():
            text = str(key).strip().lower()
            # Also accept explicit bimonthly keys (bimestre_1, bim-1, ...).
            bim = re.search(r"(?:bim(?:estre)?)[ _-]*(\d+)", text)
            if bim and int(bim.group(1)) == sequence:
                total += D(value)
                matched = True
                continue
            month = _month_from_key(key, year)
            if month is None:
                continue
            if period.period_start.month <= month <= period.period_end.month:
                total += D(value)
                matched = True
        return (total if matched else ZERO), matched

    @staticmethod
    def _period_base(period, sequence: int, lines, override, year):
        """Return (gross base, source, found). ``found`` is False only for an override without data."""
        if override is not None:
            base, found = BudgetTaxEngine._override_base(override, period, sequence, year)
            return base, "monthly_sales_taxable_base", found
        return (
            sum(
                (D(line.projected_amount) for line in lines
                 if _line_type(line) == "income"
                 and period.period_start <= line.budget_date <= period.period_end),
                ZERO,
            ),
            "budget_lines",
            True,
        )

    def calculate(self, id_budget: int, assumption, profile, persist: bool = True):
        budget = self.db.query(Budget).filter(Budget.id_budget == id_budget).first()
        if not budget:
            return None
        lines = self.db.query(BudgetLine).filter(BudgetLine.id_budget == id_budget).all()
        income = sum((D(x.projected_amount) for x in lines if _line_type(x) == "income"), ZERO)
        expenses = sum((D(x.projected_amount) for x in lines
                        if _line_type(x) in ("expense", "purchase")), ZERO)
        rates = list_tax_rates(self.db, budget.budget_year)
        calendars = list_tax_calendar(self.db, budget.budget_year, profile.regime)
        warnings = []
        results = []

        def first_calendar(typ):
            return next((c for c in calendars
                         if c.tax_type == typ
                         and getattr(c, "is_active", True)), None)

        def make(typ, base, rate_obj, caused, advance=ZERO, withholding=ZERO,
                 period=None, trace=None, extra_warnings=None, balance=None):
            cal = period or first_calendar(typ)
            row_warnings = list(extra_warnings or [])
            if cal is None:
                warning = f"Missing calendar for {typ} ({budget.budget_year})"
                warnings.append(warning)
                row_warnings.append(f"Missing calendar for {typ}")
            if rate_obj is None:
                warning = f"Missing rate for {typ} ({budget.budget_year})"
                warnings.append(warning)
                row_warnings.append(f"Missing rate for {typ}")
            trace = dict(trace or {})
            trace.setdefault(
                "accounting_classification",
                "p_and_l_expense" if typ in P_AND_L_TAX_TYPES else "cash_credit",
            )
            trace.setdefault(
                "cash_treatment",
                "advance_plus_balance" if typ in P_AND_L_TAX_TYPES else "balance_after_credits",
            )
            if cal is not None:
                trace.setdefault("period_code", cal.period_code)
                trace.setdefault("period_sequence", cal.sequence)
                trace.setdefault(
                    "declaration_date",
                    cal.declaration_due_date.isoformat()
                    if cal.declaration_due_date else None,
                )
                trace.setdefault(
                    "payment_date",
                    cal.payment_due_date.isoformat()
                    if cal.payment_due_date else None,
                )
                trace.setdefault(
                    "payment_year",
                    cal.payment_due_date.year if cal.payment_due_date
                    else cal.payment_year,
                )
            # Keep the two dimensions in the immutable calculation trace.  We
            # intentionally do not add columns to the existing snapshot table:
            # old installations can therefore read new calculations without a
            # migration, while API schemas can expose these coordinates.
            if typ in ("income_ordinary", "simple"):
                trace.setdefault("pnl_month", 12)
                trace.setdefault("pnl_year", budget.budget_year)
                trace.setdefault("pnl_basis", "budget_year_december")
            elif typ == "ica":
                pnl_date = (cal.declaration_due_date if cal and cal.declaration_due_date
                            else cal.period_end if cal else None)
                trace.setdefault("pnl_month", pnl_date.month if pnl_date else None)
                trace.setdefault("pnl_year", pnl_date.year if pnl_date else None)
                trace.setdefault("pnl_basis", "declaration_date_or_period_end")
            else:
                trace.setdefault("pnl_month", None)
                trace.setdefault("pnl_year", None)
                trace.setdefault("pnl_basis", "cash_credit_not_p_and_l")
            payment_date = cal.payment_due_date if cal else None
            results.append(dict(
                id_budget=id_budget,
                id_budget_tax_assumption=assumption.id_budget_tax_assumption,
                tax_type=typ,
                period_start=cal.period_start if cal else date(budget.budget_year, 1, 1),
                period_end=cal.period_end if cal else date(budget.budget_year, 12, 31),
                taxable_base=money(base),
                # A rate is a ratio, not a COP amount: do not quantize it to
                # two decimals (0.035 must remain 0.035).
                tax_rate=rate_decimal(rate_obj.rate) if rate_obj else ZERO,
                tax_caused=money(caused),
                advance_amount=money(advance),
                withholding_amount=money(withholding),
                balance_payable=money(balance if balance is not None
                                      else max(ZERO, caused - advance - withholding)),
                declaration_date=cal.declaration_due_date if cal else None,
                payment_date=payment_date,
                # The date is authoritative.  payment_year in old catalogs
                # can be stale and must never move a cash event to another
                # year.
                payment_year=(payment_date.year if payment_date is not None
                              else cal.payment_year if cal else None),
                calculation_trace=trace,
                warnings=row_warnings,
            ))

        if profile.regime == 'ordinary':
            fiscal = (assumption.taxable_income_override
                      if assumption.taxable_income_override is not None else
                      income - expenses + D(assumption.non_deductible_expenses)
                      - D(assumption.exempt_income)
                      + D(assumption.taxable_income_adjustments)
                      - D(assumption.tax_losses))
            fiscal = max(ZERO, fiscal)
            cal = next((c for c in calendars
                        if c.tax_type == 'income_ordinary'
                        and getattr(c, "is_active", True)), None)
            rate = self._rate(
                rates, 'income_ordinary', profile, fiscal,
                cal.period_end if cal else None,
            )
            caused = max(
                ZERO,
                self._tax_amount(fiscal, rate) - D(assumption.tax_discounts),
            )
            make(
                'income_ordinary', fiscal, rate, caused,
                assumption.prior_advances, assumption.prior_withholdings, cal,
                {
                    'income': str(income),
                    'expenses': str(expenses),
                    'fiscal_income': str(fiscal),
                    'base_source': 'budget_lines',
                    # Advances of the fiscal year are cash in December of that year
                    # (P&L uses the full caused tax in December as well); the balance
                    # keeps the calendar payment date.
                    'advance_cash_date': date(budget.budget_year, 12, 31).isoformat(),
                },
            )
        else:
            # SIMPLE is settled independently for every configured calendar
            # period (normally six bimesters).  In particular, rate lookup is
            # inside this loop: a high-income bimestre cannot push a
            # low-income bimestre into the annual bracket.
            override = assumption.monthly_sales_taxable_base
            periods = self._active_periods(calendars, 'simple', profile.regime)
            if len(periods) != 6:
                warnings.append(
                    f"SIMPLE requires six active bimonthly periods; found {len(periods)}"
                )
            # Each bimester is computed on its own base and rate.  Prior advances
            # and prior withholdings are credits: they are consumed in period order
            # until exhausted, so each bimester pays its tax minus the credit
            # applied to it.  The annual liquidation is reported on the last
            # period only; a credit larger than the annual tax is lost.
            entries = []
            if not periods:
                gross = (sum((D(value) for value in override.values()), ZERO)
                         if override is not None else income)
                rate = self._rate(rates, 'simple', profile, gross)
                entries.append({
                    'period': None, 'gross': gross, 'rate': rate,
                    'caused': self._tax_amount(gross, rate), 'warnings': [],
                    'trace': {
                        'base_source': ('monthly_sales_taxable_base'
                                        if override is not None else 'budget_lines'),
                        'period_code': 'annual_fallback',
                    },
                })
            else:
                for index, period in enumerate(periods, start=1):
                    sequence = _period_sequence(period, index)
                    gross, base_source, base_found = self._period_base(
                        period, sequence, lines, override, budget.budget_year,
                    )
                    period_warnings = []
                    if not base_found:
                        period_warnings.append(
                            f"Missing monthly sales base for {period.period_code} ({budget.budget_year})"
                        )
                        warnings.extend(period_warnings)
                    rate = self._rate(
                        rates, 'simple', profile, gross, period.period_end,
                    )
                    entries.append({
                        'period': period, 'gross': gross, 'rate': rate,
                        'caused': self._tax_amount(gross, rate),
                        'warnings': period_warnings,
                        'trace': {
                            'base_source': base_source,
                            'period_code': period.period_code,
                            'period_sequence': sequence,
                        },
                    })

            advance_left = D(assumption.prior_advances)
            withholding_left = D(assumption.prior_withholdings)
            credits_applied = ZERO
            payments = ZERO
            for entry in entries:
                caused = entry['caused']
                advance_applied = min(advance_left, caused)
                advance_left -= advance_applied
                withholding_applied = min(withholding_left, caused - advance_applied)
                withholding_left -= withholding_applied
                entry['advance_applied'] = advance_applied
                entry['withholding_applied'] = withholding_applied
                entry['payment'] = caused - advance_applied - withholding_applied
                credits_applied += advance_applied + withholding_applied
                payments += entry['payment']
            credits_lost = advance_left + withholding_left
            annual_caused = sum((entry['caused'] for entry in entries), ZERO)
            if credits_lost > 0:
                warnings.append(f"SIMPLE credits exceed the annual tax; {money(credits_lost)} is lost")

            for position, entry in enumerate(entries):
                trace = dict(entry['trace'])
                trace.update({
                    'gross_income': str(entry['gross']),
                    # SIMPLE is paid through the bimester balance on its payment
                    # date; the credits reduce that balance and are not cash.
                    'cash_advance': str(ZERO),
                    'credit_advance_applied': str(entry['advance_applied']),
                    'credit_withholding_applied': str(entry['withholding_applied']),
                })
                if position == len(entries) - 1:
                    trace['liquidation'] = {
                        'annual_caused': str(annual_caused),
                        'credits_applied': str(credits_applied),
                        'payments': str(payments),
                        'balance': str(annual_caused - credits_applied - payments),
                        'credits_lost': str(credits_lost),
                    }
                make(
                    'simple', entry['gross'], entry['rate'], entry['caused'],
                    entry['advance_applied'], entry['withholding_applied'],
                    entry['period'],
                    extra_warnings=entry['warnings'],
                    trace=trace,
                    balance=entry['payment'],
                )

        # ── Periodic obligations: ReteIVA, retention in the source, ICA, ReteICA ──
        # Every tax type follows its own calendar (bimestral/monthly as configured).
        # Bases are causation figures of each period: income and expenses by
        # budget_date, purchase IVA by event date (D-S10-9 enmendada). An
        # assumption override (withholding_base / reteica_base) keeps a single
        # annual row; without it, one result is emitted per calendar period.
        iva_events = BudgetIvaEngine(self.db).events(id_budget) or []
        purchase_iva = sum((D(event['amount']) for event in iva_events
                            if event['side'] == 'deductible'
                            and event['concept'] in PURCHASE_IVA_CONCEPTS), ZERO)

        def _income_of(period):
            return sum((D(line.projected_amount) for line in lines
                        if _line_type(line) == 'income'
                        and period.period_start <= line.budget_date <= period.period_end), ZERO)

        def _expenses_of(period):
            return sum((D(line.projected_amount) for line in lines
                        if _line_type(line) in ('expense', 'purchase')
                        and period.period_start <= line.budget_date <= period.period_end), ZERO)

        def _purchase_iva_of(period):
            return sum((D(event['amount']) for event in iva_events
                        if event['side'] == 'deductible'
                        and event['concept'] in PURCHASE_IVA_CONCEPTS
                        and period.period_start <= date.fromisoformat(event['date'])
                        <= period.period_end), ZERO)

        def emit_periodic(typ, entries, annual_credit=ZERO):
            """entries: [(period_or_None, base, base_source)].

            Credits are consumed in period order with the same contract as the
            SIMPLE calculation; a leftover no period can absorb is lost.
            """
            credit_left = annual_credit
            total_caused = ZERO
            for period, base, source in entries:
                cal = period or first_calendar(typ)
                rate = self._rate(rates, typ, profile, base,
                                  cal.period_end if cal else None)
                caused = self._tax_amount(base, rate)
                applied = min(credit_left, caused)
                credit_left -= applied
                total_caused += caused
                make(
                    typ, base, rate, caused,
                    withholding=applied,
                    period=period,
                    balance=caused - applied,
                    trace={'base_source': source},
                )
            if entries and credit_left > 0 and total_caused > 0:
                warnings.append(
                    f"{typ} credits exceed the annual tax; {money(credit_left)} is lost")

        def _periods_of(typ):
            return self._active_periods(calendars, typ, profile.regime)

        # ReteIVA is practiced by the buyer on the IVA of its purchases, not on
        # the IVA charged on sales. A non-agent keeps the single informative
        # row that carries the suffered ReteIVA credit.
        if profile.reteiva_agent:
            reteiva_periods = _periods_of('reteiva')
            emit_periodic(
                'reteiva',
                ([(period, _purchase_iva_of(period), 'purchase_iva')
                  for period in reteiva_periods]
                 if reteiva_periods else
                 [(None, purchase_iva, 'purchase_iva')]),
                D(assumption.reteiva_suffered),
            )
        elif D(assumption.reteiva_suffered) > 0:
            reteiva_cal = first_calendar('reteiva')
            rate = self._rate(rates, 'reteiva', profile, ZERO,
                              reteiva_cal.period_end if reteiva_cal else None)
            make(
                'reteiva', ZERO, rate, ZERO,
                withholding=D(assumption.reteiva_suffered),
                trace={'base_source': 'none', 'iva_source': 'suffered_credit_only'},
            )

        # Retención en la fuente: practiced on payments to third parties (the
        # budget's expenses), unless the assumption sets an explicit base.
        withholding_periods = _periods_of('withholding')
        if profile.withholding_agent:
            if assumption.withholding_base is not None or not withholding_periods:
                overridden = assumption.withholding_base is not None
                emit_periodic(
                    'withholding',
                    [(None, D(assumption.withholding_base) if overridden else expenses,
                      'assumption' if overridden else 'budget_expenses')],
                    D(assumption.withholding_suffered),
                )
            else:
                emit_periodic(
                    'withholding',
                    [(period, _expenses_of(period), 'budget_expenses')
                     for period in withholding_periods],
                    D(assumption.withholding_suffered),
                )

        # ICA: caused on the municipal base (income causation) of each configured period.
        ica_periods = _periods_of('ica')
        emit_periodic(
            'ica',
            ([(period, _income_of(period), 'budget_lines') for period in ica_periods]
             if ica_periods else [(None, income, 'budget_lines')]),
        )

        # ReteICA: an explicit override keeps one annual row; otherwise it
        # follows its calendar on the income causation of each period.
        if assumption.reteica_base is not None:
            emit_periodic('reteica', [(None, D(assumption.reteica_base), 'assumption')])
        elif profile.reteica_agent:
            reteica_periods = _periods_of('reteica')
            emit_periodic(
                'reteica',
                ([(period, _income_of(period), 'budget_lines') for period in reteica_periods]
                 if reteica_periods else [(None, income, 'budget_lines')]),
            )

        # Only the explicit calculation replaces the persisted snapshots. Read
        # only projections (e.g. the regime comparison) must not overwrite them.
        if persist:
            clear_budget_tax_results(self.db, id_budget)
            for row in results:
                add_budget_tax_result(self.db, **row)
            self.db.commit()
        public_results = [
            {
                **row,
                **tax_result_locations(
                    row,
                    budget.budget_year,
                ),
            }
            for row in results
        ]
        return {
            'id_budget': id_budget,
            'regime': profile.regime,
            'assumption': assumption,
            'warnings': warnings,
            'results': public_results,
            'totals': {
                'taxable_base': sum((row['taxable_base'] for row in results), ZERO),
                'tax_caused': sum((row['tax_caused'] for row in results), ZERO),
                'advance_amount': sum((row['advance_amount'] for row in results), ZERO),
                'withholding_amount': sum((row['withholding_amount'] for row in results), ZERO),
                'balance_payable': sum((row['balance_payable'] for row in results), ZERO),
            },
        }
