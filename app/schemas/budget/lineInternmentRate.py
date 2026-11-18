"""
LineInternmentRate Schemas (BE-S9-INTERNMENT-SPLIT)

Contract for the internment-rate catalog endpoints
(spec backend.02_19 §3.1 / §5.3). ``internment_pct`` is stored as a
FRACTION 0-1 and read as a MARK-UP OVER THE SUPPLIER COST (D-S9-1:
Total = CostoProveedor × (1 + pct)), NOT a share of the total.
Validation ``gt=0, le=1`` -> 422 outside the range: the zero-pct lower
bound is EXCLUSIVE because the absence of a rate is represented by
DELETING the row (§4 then derives pct = 0 with zero internment rows,
A-5 — a stored 0 would be a redundant row the CRUD uniqueness already
discourages), exactly mirroring the linePayableTerm.py rationale; and
``le=1`` because a mark-up above 100 % of the supplier cost is outside
the commercial range of customs/nationalization charges (amendable if a
stakeholder ever asks, backend.02_19 §3.1). One row per Line: the
``unique=True`` index is created by create_all, but the useful 400
message is produced by the CRUD guard BEFORE the IntegrityError.
"""

from pydantic import BaseModel, Field, ConfigDict


class LineInternmentRateBase(BaseModel):
    id_line: int = Field(..., gt=0, description="FK to line (lines.id_line), "
                                                "unique per Line")
    internment_pct: float = Field(
        ..., gt=0, le=1,
        description="Internment mark-up over the supplier cost (fraction "
                    "0-1, exclusive of 0, D-S9-1): Total = Prov × (1 + pct)",
    )

    model_config = ConfigDict(from_attributes=True)


class LineInternmentRateCreate(LineInternmentRateBase):
    pass


class LineInternmentRate(LineInternmentRateBase):
    id_line_internment_rate: int = Field(..., gt=0)
