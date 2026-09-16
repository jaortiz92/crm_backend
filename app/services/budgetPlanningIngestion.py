"""
Budget Planning Ingestion Service (T-02 / BR-ING-05)

Shared construction of ``budget_lines`` records from the SIIGO budget-plan
ETL outputs (``BudgetTemplates.process_budget_plan_income/expense``),
extracted verbatim from the inline loops that used to live in
``app/api/budget/upload.py``.

Consumers:
- Legacy endpoints ``POST /budget/upload/budget-plan-income`` and
  ``POST /budget/upload/budget-plan-expense`` (external behavior must stay
  IDENTICAL — AC-REG-01), which call WITHOUT ``budget_year``.
- New endpoint ``POST /budget/planning/upload`` (§5.1), which also passes
  ``budget_year`` to activate the BR-ING-06 validation. BE-S8-BUDGET-
  PURCHASES (backend.02_18 §5.3) adds the OPTIONAL third file
  ``file_compras`` via ``build_purchase_line_records`` at the bottom of
  this module: one Excel row -> one purchase budget_line, same
  all-or-nothing transaction, shared missing_cost_centers rejection
  list. AMENDMENT A-01 (backend.02_18 §10.2): purchases now carry the
  Temporada/``short_collection_name`` metadata of the real SIIGO imports
  file, resolved with the exact income/expense NON-BLOCKING pair above.

Preserved semantics (identical to the previous inline code):
- Cost-center resolution via the FIRST TOKEN of the "Centro de Costo" cell
  (produced by the ETL) through ``crud.get_cost_center_by_code``; unresolved
  rows are collected in ``missing_cost_centers`` (BR-ING-03, ASM-5) instead
  of raising, so the caller can reject atomically.
- Collection mapping via ``short_collection_name`` is NON-BLOCKING:
  unknown season -> ``id_collection = None`` (same as today).
- BR-ING-05 (income): ``line_payment_rules`` of the cost-center's product
  line split ONE Excel row into N budget lines with staggered
  ``payment_date = budget_date + payment_days`` and
  ``projected_amount * payment_pct``. A single rule with 0 days keeps the
  row as one line with ``payment_date = budget_date``. (UNTOUCHED by
  BE-S7: the stakeholder confirmed collection installments stay.)
- BE-S5-PAYABLE-TERMS expense expansion (BR-TERM-02..04/07/09, the
  ``expand_payable_terms`` opt-in flag and the shared
  ``expand_expense_line`` helper) was FULLY ROLLED BACK by
  BE-S7-COGS-PAYFLOW (backend.02_17 §2, D-S7-6): a fixed expense is paid
  WHOLE again — ONE row, ``payment_date`` straight from the record. Both
  callers (planning upload and legacy upload.py:416) are therefore
  byte-identical to each other and to the pre-S5 output again
  (AC-REG-01 / AC-S7-BE-2). The ``line_payable_terms`` catalog REMAINS
  alive, re-semantized (D-S7-1) as the terms with which WE PAY the
  supplier the COGS of a Line: consumed only by the server-side carryover
  derivation (backend.02_17 §4) and the FE-S7 live Vista Flujo — never
  materialized into ``budget_lines`` here.
- Expense: ``behavior_type`` comes from the ETL; non-fixed rows carry the
  rate in ``variable_rate`` and ``projected_amount = 0`` (legacy conditional
  logic in budgetTemplates.py:1480-1485, re-applied here for safety).

No commit/rollback happens in this module: it is pure in-memory building on
top of read-only queries (T-05 — the caller owns the transaction).
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

import app.crud as crud


class BudgetYearMismatchError(Exception):
    """BR-ING-06: processed rows carry a year(budget_date) different from
    the declared ``budget_year``. ``found_years`` lists the offending years
    (sorted, unique) for the structured 400 response (§5.1/§4.3)."""

    def __init__(self, found_years: List[int]):
        self.found_years = sorted(found_years)
        super().__init__(
            f"Rows outside declared budget_year: {self.found_years}"
        )


def _as_date(value: Any) -> Any:
    """Parse an ETL date cell exactly like the legacy inline code did
    (ISO string -> date; date/NaT passthrough)."""
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return value


def _check_row_year(
    budget_date: Any, budget_year: Optional[int], found_years: set
) -> None:
    """BR-ING-06 accumulator: only enforced when ``budget_year`` is given
    (planning upload). Legacy calls pass None and skip validation entirely,
    keeping AC-REG-01 behavior."""
    if budget_year is not None and isinstance(budget_date, date) \
            and budget_date.year != budget_year:
        found_years.add(budget_date.year)


def build_income_line_records(
    db: Session,
    records: List[Dict[str, Any]],
    id_budget: int,
    budget_year: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build income ``budget_lines`` dicts from processed Excel records.

    Returns ``(budget_lines_data, missing_cost_centers)`` — same content and
    order as the loop previously inlined in upload.py (§313-425). Raises
    ``BudgetYearMismatchError`` (BR-ING-06) only when ``budget_year`` is
    provided and some row falls outside it.
    """
    missing_cost_centers: List[str] = []
    budget_lines_data: List[Dict[str, Any]] = []
    found_years: set = set()

    for record in records:
        cc_code = record.get("id_cost_center_code")
        cc = crud.get_cost_center_by_code(db, cc_code)
        if not cc:
            missing_cost_centers.append(cc_code)
            continue

        coll_short = record.get("short_collection_name")
        coll = crud.get_collection_by_short_name(db, coll_short)
        id_collection = coll.id_collection if coll else None

        budget_date = _as_date(record.get("budget_date"))
        _check_row_year(budget_date, budget_year, found_years)

        id_line = cc.id_line
        payment_date = budget_date

        if id_line:
            rules = crud.get_line_payment_rules_by_line(db, id_line)
            if rules:
                if len(rules) == 1 and rules[0].payment_days == 0:
                    payment_date = budget_date
                else:
                    for rule in rules:
                        rule_payment_date = budget_date + timedelta(
                            days=rule.payment_days
                        )
                        partial_amount = (
                            record.get("projected_amount", 0) * rule.payment_pct
                        )
                        budget_lines_data.append({
                            "id_budget": id_budget,
                            "id_cost_center": cc.id_cost_center,
                            "line_type": "income",
                            "budget_date": budget_date,
                            "payment_date": rule_payment_date,
                            "id_collection": id_collection,
                            "projected_amount": partial_amount,
                            "description": record.get("description"),
                            "behavior_type": "fixed",
                        })
                    continue

        budget_lines_data.append({
            "id_budget": id_budget,
            "id_cost_center": cc.id_cost_center,
            "line_type": "income",
            "budget_date": budget_date,
            "payment_date": payment_date,
            "id_collection": id_collection,
            "projected_amount": record.get("projected_amount", 0),
            "description": record.get("description"),
            "behavior_type": "fixed",
        })

    if found_years:
        raise BudgetYearMismatchError(found_years)

    return budget_lines_data, missing_cost_centers


def build_expense_line_records(
    db: Session,
    records: List[Dict[str, Any]],
    id_budget: int,
    budget_year: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build expense ``budget_lines`` dicts from processed Excel records.

    Returns ``(budget_lines_data, missing_cost_centers)`` — same content and
    order as the loop previously inlined in upload.py (§428-528). Raises
    ``BudgetYearMismatchError`` (BR-ING-06) only when ``budget_year`` is
    provided and some row falls outside it.

    BE-S7-COGS-PAYFLOW §2 rollback: the BE-S5 ``expand_payable_terms``
    opt-in parameter and the installment expansion through
    ``line_payable_terms`` are RETIRED — a fixed expense stays ONE row
    with the ``payment_date`` of the record as-is (BR-TERM-02..04/07/09
    superseded). Planning and legacy outputs are identical again; no
    caller passes any expansion flag.
    """
    missing_cost_centers: List[str] = []
    budget_lines_data: List[Dict[str, Any]] = []
    found_years: set = set()

    for record in records:
        cc_code = record.get("id_cost_center_code")
        cc = crud.get_cost_center_by_code(db, cc_code)
        if not cc:
            missing_cost_centers.append(cc_code)
            continue

        coll_short = record.get("short_collection_name")
        coll = crud.get_collection_by_short_name(db, coll_short)
        id_collection = coll.id_collection if coll else None

        budget_date = _as_date(record.get("budget_date"))
        _check_row_year(budget_date, budget_year, found_years)

        payment_date = _as_date(record.get("payment_date"))

        behavior_type = record.get("behavior_type", "fixed")
        projected_amount = record.get("projected_amount", 0)
        variable_rate = record.get("variable_rate")

        if behavior_type != "fixed" and variable_rate is not None:
            projected_amount = 0

        budget_lines_data.append({
            "id_budget": id_budget,
            "id_cost_center": cc.id_cost_center,
            "line_type": "expense",
            "budget_date": budget_date,
            "payment_date": payment_date,
            "id_collection": id_collection,
            "projected_amount": projected_amount,
            "description": record.get("description"),
            "behavior_type": behavior_type,
            "variable_rate": variable_rate,
        })

    if found_years:
        raise BudgetYearMismatchError(found_years)

    return budget_lines_data, missing_cost_centers


def build_purchase_line_records(
    db: Session,
    records: List[Dict[str, Any]],
    id_budget: int,
    budget_year: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build PURCHASE ``budget_lines`` dicts from the processed imports
    template (BE-S8-BUDGET-PURCHASES §5.3, output of
    ``BudgetTemplates.process_budget_plan_purchase``).

    Same income/expense builder pattern, deliberately simpler:
    - CECO resolved by the FIRST TOKEN of "Centro de Costo" through
      ``crud.get_cost_center_by_code``; unresolved codes are APPENDED to
      the caller's single ``missing_cost_centers`` rejection list
      (BR-ING-03 — purchases share one rejection payload with the other
      two files, spec §5.3).
    - ONE Excel row == ONE purchase budget_line. NO installment
      expansion of any kind, ever (BR-PUR-05 derives them at read time;
      materializing them here would violate NFR-BE8-1).
    - ``payment_date``/``variable_rate`` are forced NULL and
      ``behavior_type`` FIXED (BR-PUR-01 row semantics). AMENDMENT A-01
      (backend.02_18 §10.2): ``id_collection`` is now a legal season
      metadata on purchases — resolved with the EXACT income/expense
      parity pair (l.116-118): unknown/empty ``short_collection_name``
      -> ``id_collection = None`` WITHOUT blocking (a purchase row never
      expands: one Excel row stays one purchase line).
    - ``budget_date`` = the IMPORT date and BR-ING-06 applies to it
      (``_check_row_year`` -> ``BudgetYearMismatchError`` with the
      aggregated ``found_years``, 400 + total rollback in the endpoint).

    No commit here (T-05): the records join the same
    ``create_budget_lines_bulk`` single transaction as income+expense
    (all-or-nothing, R-ING-01/B)."""
    missing_cost_centers: List[str] = []
    budget_lines_data: List[Dict[str, Any]] = []
    found_years: set = set()

    for record in records:
        cc_code = record.get("id_cost_center_code")
        cc = crud.get_cost_center_by_code(db, cc_code)
        if not cc:
            missing_cost_centers.append(cc_code)
            continue

        # A-01 §10.2: season (Temporada) with the exact income pair —
        # NON-BLOCKING: unknown/empty short name -> id_collection NULL.
        coll_short = record.get("short_collection_name")
        coll = crud.get_collection_by_short_name(db, coll_short)
        id_collection = coll.id_collection if coll else None

        # BR-ING-06 over the import date (the purchase budget_date).
        budget_date = _as_date(record.get("budget_date"))
        _check_row_year(budget_date, budget_year, found_years)

        budget_lines_data.append({
            "id_budget": id_budget,
            "id_cost_center": cc.id_cost_center,
            "line_type": "purchase",
            "budget_date": budget_date,
            "payment_date": None,
            "id_collection": id_collection,
            "projected_amount": record.get("projected_amount", 0),
            "description": record.get("description"),
            "behavior_type": "fixed",
        })

    if found_years:
        raise BudgetYearMismatchError(found_years)

    return budget_lines_data, missing_cost_centers
