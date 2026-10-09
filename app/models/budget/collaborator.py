"""
Collaborator Models (BE-S11-COLLABORATORS, spec backend.02_21 §4.1-§4.6)

Six tables of the payroll cost module:

- collaborators                 master, ONE cost center per collaborator (A-09)
- collaborator_salary_plans     salary vigencias (history, BR-COLLAB-02)
- labor_cost_parameters         key/value annual parameters per vigencia (A-02)
- labor_arl_rates               ARL rate per vigencia and risk class (§4.4)
- cost_components               catalog of CAJA/PROVISION components (§4.5)
- collaborator_provision_accruals  monthly causacion ledger, payment seat =
                                   accrued - paid (D-S11-3)

D-S11-2: low-cardinality enums (contract_type, status, layer, doc_type) are
plain String columns validated by pydantic ``Literal`` — NO Postgres enum
types (the painful ``linetypeenum`` precedent: ALTER TYPE manual drills).
D-S11-4: money is Numeric(15,2)/Decimal end-to-end; rates DECIMAL(9,6);
Float is forbidden here (the ``amount Float`` of ActualCost is NOT the model
to imitate). Tables are auto-created by ``Base.metadata.create_all`` (new
tables, zero manual DDL — the only ALTER of this feature is budget_lines,
see §4.7/§4.8 and note.md).
"""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class Collaborator(Base):
    """Master of collaborators (§4.1). doc_value is the natural upsert key
    of the payroll template (R-07). salary lives in the plans, never here."""
    __tablename__ = "collaborators"

    id_collaborator = Column(Integer, primary_key=True, index=True)
    doc_type = Column(String(4), nullable=False, server_default="CC")  # CC|CE|NIT
    doc_value = Column(String(20), unique=True, index=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    # 1 CECO per collaborator (A-09): no % split in v1.
    id_cost_center = Column(
        Integer, ForeignKey("cost_centers.id_cost_center"), nullable=False
    )
    # D-S11-2: open_ended | fixed_term | work_or_service | service_provision
    contract_type = Column(String(30), nullable=False)
    # active | terminated
    status = Column(String(12), nullable=False, server_default="active")
    hire_date = Column(Date, nullable=False)
    termination_date = Column(Date, nullable=True)
    # I..V; NULL => arl_default_class parameter of the vigencia (§4.3)
    risk_class = Column(String(3), nullable=True)
    # temporada default (NULL ok). Spec says "product_collections"; the
    # actual catalog table of this repo is `collections` (income/expense/
    # purchase ETL parity via short_collection_name).
    id_collection = Column(
        Integer, ForeignKey("collections.id_collection"), nullable=True
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    cost_center = relationship("CostCenter")
    collection = relationship("Collection")
    salary_plans = relationship(
        "CollaboratorSalaryPlan",
        back_populates="collaborator",
        order_by="CollaboratorSalaryPlan.valid_from",
        cascade="all, delete-orphan",
    )
    provision_accruals = relationship(
        "CollaboratorProvisionAccrual",
        back_populates="collaborator",
        cascade="all, delete-orphan",
    )


class CollaboratorSalaryPlan(Base):
    """Salary vigencia (§4.2). The OPEN plan (valid_to NULL) is the current
    one; a raise CLOSES it (valid_to = new valid_from - 1) instead of
    editing history (BR-02/BR-COLLAB-02). allowance_non_salary NEVER
    enters the IBC nor any benefit base (BR-11)."""
    __tablename__ = "collaborator_salary_plans"

    id_salary_plan = Column(Integer, primary_key=True, index=True)
    id_collaborator = Column(
        Integer, ForeignKey("collaborators.id_collaborator"), nullable=False
    )
    salary = Column(Numeric(15, 2), nullable=False)  # honorarios in service
    allowance_salary = Column(Numeric(15, 2), nullable=False, server_default="0")
    allowance_non_salary = Column(Numeric(15, 2), nullable=False, server_default="0")
    is_integral = Column(Boolean, nullable=False, server_default="False")
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date, nullable=True)  # NULL = open (BR-COLLAB-02)
    created_at = Column(DateTime, server_default=func.now())

    collaborator = relationship("Collaborator", back_populates="salary_plans")

    __table_args__ = (
        CheckConstraint("salary > 0", name="ck_salary_plan_salary_positive"),
        UniqueConstraint(
            "id_collaborator", "valid_from",
            name="uq_salary_plan_collaborator_valid_from",
        ),
    )


class LaborCostParameter(Base):
    """Key/value labor parameters per annual vigencia (§4.3, A-02/A-11).
    Values are stored as short strings (SMLV "1500000.00", dates "06-30",
    day "last_business_day" or "5") and parsed to Decimal by the engine —
    string keeps zero float in the money path (D-S11-4)."""
    __tablename__ = "labor_cost_parameters"

    id = Column(Integer, primary_key=True, index=True)
    vigencia = Column(Integer, nullable=False)
    key = Column(String(60), nullable=False)
    value = Column(String(60), nullable=False)

    __table_args__ = (
        UniqueConstraint("vigencia", "key", name="uq_labor_params_vigencia_key"),
    )


class LaborArlRate(Base):
    """ARL rate per vigencia and risk class I..V (§4.4)."""
    __tablename__ = "labor_arl_rates"

    id = Column(Integer, primary_key=True, index=True)
    vigencia = Column(Integer, nullable=False)
    risk_class = Column(String(3), nullable=False)
    rate = Column(Numeric(9, 6), nullable=False)

    __table_args__ = (
        UniqueConstraint("vigencia", "risk_class", name="uq_arl_rates_vigencia_class"),
    )


class CostComponent(Base):
    """Catalog of cost components (§4.5), seeded (phase 3 §4.8). layer is
    CAJA (paid monthly) or PROVISION (caused monthly, paid on the legal
    date). The two extralegales are seeded is_active=False (A-11/R-12) —
    the engine only emits active components."""
    __tablename__ = "cost_components"

    code = Column(String(20), primary_key=True)  # PK is the code (§4.5)
    name = Column(String(80), nullable=False)
    layer = Column(String(12), nullable=False)  # CAJA | PROVISION
    formula_key = Column(String(40), nullable=True)
    is_legal = Column(Boolean, nullable=False, server_default="True")
    is_active = Column(Boolean, nullable=False, server_default="True")
    payment_date_key = Column(String(40), nullable=True)  # params key


class CollaboratorProvisionAccrual(Base):
    """Monthly causacion ledger of the PROVISION layer (§4.6, D-S11-3).
    The payment seat is ALWAYS ``acruado_acumulado - pagado`` (never
    recomputed from the rate), and the last payment of a period closes the
    balance to exactly 0. ``paid`` is marked by the engine only — there is
    no real payment in the CRM (A-05)."""
    __tablename__ = "collaborator_provision_accruals"

    id = Column(Integer, primary_key=True, index=True)
    id_collaborator = Column(
        Integer, ForeignKey("collaborators.id_collaborator"), nullable=False
    )
    component_code = Column(String(20), ForeignKey("cost_components.code"), nullable=False)
    period_month = Column(Date, nullable=False)  # 1st day of the month
    accrued = Column(Numeric(15, 2), nullable=False, server_default="0")
    paid = Column(Numeric(15, 2), nullable=False, server_default="0")
    params_vigencia = Column(Integer, nullable=False)  # NFR-03 reproducibility

    collaborator = relationship("Collaborator", back_populates="provision_accruals")
    component = relationship("CostComponent")

    __table_args__ = (
        UniqueConstraint(
            "id_collaborator", "component_code", "period_month",
            name="uq_accrual_collab_component_month",
        ),
    )
