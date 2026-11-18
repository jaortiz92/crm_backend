"""CECO bucket resolution (Enmienda A-01, spec backend.02_24 §10).

Why this module exists: the plan of accounts DECOUPLES the income CECOs
("Facturación …", codes 000xxx, ids 151–181 in the real 573 scenario)
from the variable-expense CECOs ("Comisiones …" 210xxx / "Despacho …"
320xxx, ids 8–120). A variable-expense budget line therefore carries an
``id_cost_center`` that by design has NO income of its own, so a naive
``I_c(m)`` base produced 0 for every variable line.

The shared rule (spec §10.2), used 1:1 by ``budgetEngine.project_cash_flow``
(B1/B2) and ``budgetIvaEngine`` (E3/E4):

1. OWN CECO first (compat): if the line's CECO already has an income
   base, resolve to itself.
2. Else the (id_zone, id_line) bucket of the line's CECO — resolvable
   ONLY when the bucket has EXACTLY ONE income CECO.
3. No fallback (zero rule): 0 or multiple generators, unknown CECO, or
   NULL zone/line ⇒ None ⇒ the line contributes 0. Never an error, never
   a global or zone-wide fallback.

Pure dict helpers over the per-CECO mirrors the engines already build:
ONE extra catalog query per engine call, no new JOINs, no N+1.
"""

from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.budget import CostCenter


def load_ceco_bucket_catalog(db: Session) -> Dict[int, tuple]:
    """Enmienda A-01 (spec backend.02_24 §10): one-query catalog
    ``ceco_id -> (id_zone, id_line)`` used by the (zone, line) bucket
    resolution of the variable-expense bases. Cost centers whose zone or
    line is NULL are EXCLUDED from the catalog — they simply cannot
    participate in any bucket (they would only ever resolve through
    their own CECO path)."""
    rows = (
        db.query(
            CostCenter.id_cost_center,
            CostCenter.id_zone,
            CostCenter.id_line,
        ).all()
    )
    return {
        int(r.id_cost_center): (r.id_zone, r.id_line)
        for r in rows
        if r.id_zone is not None and r.id_line is not None
    }


def build_ceco_buckets(
    ceco_by_month: Dict[int, Dict[int, float]],
    ceco_catalog: Dict[int, tuple],
) -> tuple:
    """Derive the (zone, line) buckets from a per-CECO mirror by dict
    passes (no extra SQL, spec §10.2). Keyed by int-tuple ``tk`` =
    (id_zone, id_line); every key component is a plain int (the catalog
    already dropped NULL zone/line, so no None can sneak into a key and
    bucket keys can never mix types).

    Args:
        ceco_by_month: ``ceco -> {month: amount}`` mirror
            (``income_ceco_by_month`` by budget_date, or the COLLECTION
            mirror ``cash_received_ceco_by_month`` by
            coalesce(payment_date, budget_date) of Enmienda A-02 §11).
        ceco_catalog: output of ``load_ceco_bucket_catalog``.

    Returns:
        tuple ``(bucket_by_month, bucket_cecos)``:
        - ``bucket_by_month``: ``tk -> {month: Σ}`` — same monthly map
          shape as the per-CECO mirrors.
        - ``bucket_cecos``: ``tk -> set(ceco generators)`` — the CECOs
          feeding the bucket, so the resolver can demand EXACTLY ONE.
    """
    bucket_by_month: Dict[tuple, Dict[int, float]] = {}
    bucket_cecos: Dict[tuple, set] = {}
    for ceco, mmap in ceco_by_month.items():
        tk = ceco_catalog.get(ceco)
        if tk is None:
            continue
        bucket_cecos.setdefault(tk, set()).add(ceco)
        bmap = bucket_by_month.setdefault(tk, {m: 0.0 for m in range(1, 13)})
        for m, v in mmap.items():
            bmap[m] += v
    return bucket_by_month, bucket_cecos


def resolve_income_ceco(
    ceco_id: Optional[int],
    income_ceco_by_month: Dict[int, Dict[int, float]],
    income_bucket_cecos: Dict[tuple, set],
    ceco_catalog: Dict[int, tuple],
) -> Optional[int]:
    """Enmienda A-01 (spec backend.02_24 §10.2): which CECO holds the
    income base of a variable-expense line.

    1. Own CECO first (compat): a variable line placed directly on a
       billing CECO keeps working unchanged.
    2. Else the CECO's (zone, line) bucket — the base is taken from the
       SINGLE billing CECO of that zone+line.
    3. No fallback (zero rule): zero or multiple generators, an unknown
       CECO, or NULL zone/line ⇒ None (contributes 0, never an error).

    The resolution is keyed on the INCOME generators exclusively; the
    caller then takes the base (income by budget_date for B1/E3, or the
    collections by payment month of Enmienda A-02 §11 for B2/E4) from the
    RESOLVED CECO's mirror. Because the resolver returns a SINGLE
    generator CECO, the amount of that CECO already IS the (zone, line)
    bucket amount — no separate bucket mirror of the collections is
    needed."""
    if ceco_id is None:
        return None
    if ceco_id in income_ceco_by_month:
        return ceco_id
    tk = ceco_catalog.get(int(ceco_id))
    if tk is None:
        return None
    generators = income_bucket_cecos.get(tk)
    if generators is not None and len(generators) == 1:
        return next(iter(generators))
    return None
