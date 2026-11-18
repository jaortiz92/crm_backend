"""
IVA Settlement API (BE-S10-IVA, spec backend.02_20 §5.9)

GET /budget/iva/settlement/{id_budget}?year= — the PROJECTED settlement
of one scenario (D-S10-12): BudgetIvaEngine pure READ derivation over
the scenario's own lines (E1..E6 of §4) and the year's iva_periods
calendar. Mounted at /budget/iva by the budget aggregator; the engine
materializes nothing (NFR-BE10-1) and budgetEngine/carryover stay
untouched (§2 exclusions).

Stack: JWT-only (get_db + get_current_user, no role gate — NFR-BE10-6).
The 404 is resolved HERE from the CRUD Optional->None convention with
the EXACT §5.9 literal "Budget {id_budget} not found" (quoted by the
spec, wins over the generic Exceptions wording — lineInternmentRate.py
precedent). ``year`` is an optional override of budget.budget_year
validated [2000, 2100] (422 outside, §5.9); without it the liquidation
uses the scenario's own fiscal year.

Graceful degradations (NFR-BE10-3 — never a 500/422): no calendar for
the year => 200 with ``periods: []``, every event in ``unassigned`` and
the §4.4 literal warning; a scenario without lines => 200 all-zeros
with the calendar periods present.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.schemas import User, IvaSettlementResult
from app import get_db
from app.core.auth import get_current_user
from app.services.budgetIvaEngine import BudgetIvaEngine
import app.crud as crud

router = APIRouter()


@router.get("/settlement/{id_budget}", response_model=IvaSettlementResult)
def get_iva_settlement(
    id_budget: int,
    year: Optional[int] = Query(
        None, ge=2000, le=2100,
        description="Settlement fiscal year (default: budget.budget_year). "
                    "Events whose movement date falls outside THIS year are "
                    "excluded and counted in meta.out_of_year_events (§4.4).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Projected IVA settlement of the scenario (response contract
    §4.6 — IvaSettlementResult). 404 "Budget {id_budget} not found" via
    the CRUD Optional->None read (§5.9); 422 when year ∉ [2000, 2100].
    See app/services/budgetIvaEngine.py for the E1..E6 derivation, the
    §4.4 first-cover period assignment and the §4.5 unlimited-carryover
    recurrence."""
    db_budget = crud.get_budget_by_id(db, id_budget)
    if db_budget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Budget {id_budget} not found",
        )
    result = BudgetIvaEngine(db).settlement(id_budget, year=year)
    if result is None:
        # Defensive: the read-only engine could only lose the budget
        # between the guard and the derivation (practically impossible
        # under the FK graph; same Optional->None literal).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Budget {id_budget} not found",
        )
    return result
