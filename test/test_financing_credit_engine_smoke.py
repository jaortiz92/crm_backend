"""Deterministic formula/workflow smoke checks; no external DB/network required."""

from datetime import date
from decimal import Decimal
import unittest

from app.services.budget.financingCreditEngine import (
    FinancingScheduleError,
    generate_schedule,
    monthly_rate,
)


def _schedule(method, rate="0", convention="nominal_annual", first_due=date(2026, 1, 31), n=12):
    return generate_schedule(
        opening_balance=Decimal("1200000.00"),
        annual_rate=Decimal(rate),
        rate_convention=convention,
        day_count_convention="monthly_periodic",
        method=method,
        term_installments=n,
        first_due_date=first_due,
        schedule_start_date=date(2025, 12, 31),
        insurance_per_installment=Decimal("1250.00"),
    )


def test_zero_rate_french_and_german_reconcile_principal():
    for method in ("french_fixed_payment", "german_fixed_principal"):
        rows = _schedule(method)
        assert len(rows) == 12
        assert sum((row.principal_amount for row in rows), Decimal("0")) == Decimal("1200000.00")
        assert all(row.interest_amount == Decimal("0.00") for row in rows)
        assert rows[-1].closing_balance == Decimal("0.00")
        assert all(row.insurance_amount == Decimal("1250.00") for row in rows)


def test_french_payment_and_german_principal_characteristics():
    french = _schedule("french_fixed_payment", "0.12", n=6)
    german = _schedule("german_fixed_principal", "0.12", n=6)
    french_payments = [row.principal_amount + row.interest_amount for row in french]
    assert max(french_payments) - min(french_payments) <= Decimal("0.02")
    assert all(row.principal_amount == Decimal("200000.00") for row in german[:-1])
    assert german[0].interest_amount > german[-1].interest_amount
    assert sum((row.principal_amount for row in german), Decimal("0")) == Decimal("1200000.00")


def test_month_end_schedule_preserves_preferred_day_and_is_future_only():
    rows = _schedule("german_fixed_principal", first_due=date(2026, 1, 31), n=3)
    assert [row.period_end for row in rows] == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    ]
    assert all(row.period_end > date(2025, 12, 31) for row in rows)


def test_rate_convention_is_explicit_and_unsupported_day_count_rejected():
    nominal = monthly_rate(Decimal("0.12"), "nominal_annual", "monthly_periodic")
    effective = monthly_rate(Decimal("0.12"), "effective_annual", "monthly_periodic")
    assert nominal == Decimal("0.01")
    assert effective > Decimal("0.009") and effective < Decimal("0.01")
    try:
        monthly_rate(Decimal("0.12"), "nominal_annual", "actual_365")
    except FinancingScheduleError as exc:
        assert "monthly_periodic" in str(exc)
    else:
        raise AssertionError("unsupported day count must fail rather than be inferred")


def test_legacy_first_due_on_or_before_cutoff_fails_without_schedule():
    try:
        generate_schedule(
            opening_balance="1000000", annual_rate="0.18",
            rate_convention="nominal_annual",
            day_count_convention="monthly_periodic",
            method="french_fixed_payment", term_installments=12,
            first_due_date=date(2026, 3, 15),
            schedule_start_date=date(2026, 3, 15),
        )
    except FinancingScheduleError as exc:
        assert "after" in str(exc)
    else:
        raise AssertionError("legacy first installment must be strictly after cutoff")


def test_create_materializes_only_finance_expenses_and_recalculate_is_idempotent():
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models import FinancingCredit, FinancingCreditInstallment
    from app.models.budget import Budget, BudgetLine, CostCenter
    from app.models.budget.budgetLine import BehaviorTypeEnum, LineTypeEnum
    from app.schemas.budget.financingCredit import FinancingCreditCreate
    from app.services.budget.financingCreditService import (
        close_financing_credit, create_financing_credit,
        preview_financing_credit, recalculate_financing_credit,
        update_financing_credit,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(CostCenter(
            id_cost_center=1, cost_center_code="FIN-SMOKE",
            cost_center_name="Financing smoke",
        ))
        session.add(Budget(
            id_budget=1, budget_name="Financing smoke budget",
            budget_year=2026, budget_period="annual", status="active",
            is_scenario=False,
        ))
        session.commit()
        payload = FinancingCreditCreate(
            name="Smoke loan", lender_name="Smoke bank", origin_type="new",
            id_cost_center=1, method="french_fixed_payment",
            disbursement_date=date(2026, 1, 31),
            original_principal=Decimal("100000.00"),
            opening_balance=Decimal("100000.00"),
            annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
            term_installments=2,
            insurance_per_installment=Decimal("100.00"),
        )
        assert payload.frequency == "monthly"
        assert payload.day_count_convention == "monthly_periodic"
        assert payload.first_due_date is None
        preview = preview_financing_credit(session, payload)
        assert len(preview["schedule"]) == 2
        assert preview["conditions"].first_due_date == date(2026, 2, 28)
        assert [row["principal_due_date"] for row in preview["schedule"]] == [
            date(2026, 2, 28), date(2026, 3, 31),
        ]
        assert session.query(FinancingCredit).count() == 0
        invalid_convention = payload.model_copy(
            update={"day_count_convention": "actual_365"},
        )
        try:
            preview_financing_credit(session, invalid_convention)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("unsupported day-count must be an explicit HTTP 400")
        assert session.query(FinancingCredit).count() == 0
        credit, result = create_financing_credit(session, payload)
        session.commit()
        assert credit.first_due_date == preview["conditions"].first_due_date
        assert result["created_installments"] == 2
        assert result["created_budget_lines"] == 4
        lines = session.query(BudgetLine).all()
        assert len(lines) == 4
        assert {line.cost_component_code for line in lines} == {
            "FIN_INTEREST", "FIN_INSURANCE",
        }
        assert all(line.source_engine == "financing_credit" for line in lines)
        first_schedule = session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
            schedule_revision=credit.schedule_revision,
        ).all()
        assert sum((line.projected_amount for line in lines), Decimal("0")) == sum(
            (row.interest_amount + row.insurance_amount for row in first_schedule),
            Decimal("0"),
        )
        session.add_all([
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 1),
                projected_amount=Decimal("33.00"), source_engine=None,
                description="manual must survive regeneration",
            ),
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 1),
                projected_amount=Decimal("44.00"), source_engine="other_engine",
                source_engine_id=91, description="other engine must survive",
            ),
        ])
        session.commit()
        _updated_credit, update_result = update_financing_credit(
            session, credit.id_financing_credit,
            {"insurance_per_installment": Decimal("200.00")},
        )
        session.commit()
        assert update_result["replaced_installments"] == 2
        assert update_result["created_installments"] == 2
        assert update_result["replaced_budget_lines"] == 4
        assert update_result["created_budget_lines"] == 4
        preserved = session.query(BudgetLine).filter(
            BudgetLine.source_engine.is_distinct_from("financing_credit")
        ).all()
        assert {line.description for line in preserved} == {
            "manual must survive regeneration", "other engine must survive",
        }
        active_query = lambda: session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
            schedule_revision=credit.schedule_revision,
        ).order_by(FinancingCreditInstallment.installment_number).all()
        ids_before = [row.id_financing_credit_installment for row in active_query()]
        again = recalculate_financing_credit(session, credit.id_financing_credit)
        session.commit()
        ids_after = [row.id_financing_credit_installment for row in active_query()]
        assert ids_after == ids_before
        assert again["created_installments"] == 0
        assert again["created_budget_lines"] == 0
        assert session.query(FinancingCredit).count() == 1
        assert session.query(FinancingCreditInstallment).count() == 4
        try:
            close_financing_credit(
                session, credit.id_financing_credit, date(2026, 3, 1),
                Decimal("1.00"),
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("positive remaining balance must not be silently closed")
        assert credit.status == "active"
        assert session.query(BudgetLine).count() == 6
        closed, suspended_count = close_financing_credit(
            session, credit.id_financing_credit, date(2026, 3, 1), Decimal("0.00"),
        )
        session.commit()
        assert closed.status == "closed" and suspended_count == 2
        assert session.query(BudgetLine).count() == 2
        assert session.query(FinancingCreditInstallment).filter_by(
            projection_status="suspended",
        ).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_draft_budget_uses_read_only_simulation_not_materialization():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models.budget import (
        Budget, BudgetLine, CostCenter, FinancingCreditInstallment,
    )
    from app.schemas.budget.financingCredit import FinancingCreditCreate
    from app.services.budget.financingCreditService import (
        create_financing_credit, recalculate_financing_credit, serialize_credit,
    )
    from app.api.budget.planning import planning_financing_simulation

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(CostCenter(
            id_cost_center=1, cost_center_code="FIN-DRAFT-SMOKE",
            cost_center_name="Financing draft smoke",
        ))
        session.commit()

        payload = FinancingCreditCreate(
            name="Draft fallback loan", lender_name="Smoke bank", origin_type="new",
            id_cost_center=1, method="french_fixed_payment",
            disbursement_date=date(2026, 1, 31),
            original_principal=Decimal("100000.00"),
            opening_balance=Decimal("100000.00"),
            annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
            term_installments=2,
            insurance_per_installment=Decimal("100.00"),
        )
        credit, created = create_financing_credit(session, payload)
        second_credit, _second_created = create_financing_credit(
            session, payload.model_copy(update={
                "name": "Second draft loan",
                "original_principal": Decimal("50000.00"),
                "opening_balance": Decimal("50000.00"),
                "insurance_per_installment": Decimal("50.00"),
            }),
        )
        session.commit()

        installment_query = lambda: session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
            schedule_revision=credit.schedule_revision,
        ).order_by(FinancingCreditInstallment.installment_number).all()
        ids_before = [row.id_financing_credit_installment for row in installment_query()]
        assert len(ids_before) == 2
        assert created["created_budget_lines"] == 0
        assert session.query(BudgetLine).count() == 0
        assert any("simulated in draft/closed budgets" in warning
                   for warning in created["warnings"])

        session.add_all([
            Budget(
                id_budget=4, budget_name="Draft", budget_year=2026,
                budget_period="annual", status="draft", is_scenario=False,
            ),
            Budget(
                id_budget=3, budget_name="Closed", budget_year=2026,
                budget_period="annual", status="closed", is_scenario=False,
            ),
        ])
        session.commit()

        # Credit created/updated/recalculated while only drafts exist must
        # not write budget_lines. The planning endpoint derives display rows.
        lines_before_read = session.query(BudgetLine).count()
        simulation = planning_financing_simulation(4, session, None)
        assert session.query(BudgetLine).count() == lines_before_read == 0
        assert simulation.id_budget == 4
        assert simulation.budget_year == 2026
        assert simulation.financing_credits_count == 2
        assert len(simulation.lines) == 8
        assert {line.id_financing_credit for line in simulation.lines} == {
            credit.id_financing_credit, second_credit.id_financing_credit,
        }
        assert {line.cost_component_code for line in simulation.lines} == {
            "FIN_INTEREST", "FIN_INSURANCE",
        }
        assert all(line.id_cost_center == 1 for line in simulation.lines)
        expected_amounts = {}
        expected_dates = {}
        for loan in (credit, second_credit):
            installments = session.query(FinancingCreditInstallment).filter_by(
                id_financing_credit=loan.id_financing_credit,
                schedule_revision=loan.schedule_revision,
            ).all()
            expected_amounts[loan.id_financing_credit] = {
                (row.id_financing_credit_installment, code): amount
                for row in installments
                for code, amount in (
                    ("FIN_INTEREST", row.interest_amount),
                    ("FIN_INSURANCE", row.insurance_amount),
                )
            }
            expected_dates[loan.id_financing_credit] = {
                (row.id_financing_credit_installment, code): due_date
                for row in installments
                for code, due_date in (
                    ("FIN_INTEREST", row.interest_due_date),
                    ("FIN_INSURANCE", row.insurance_due_date),
                )
            }
        for line in simulation.lines:
            assert line.amount == expected_amounts[line.id_financing_credit][
                (line.id_financing_credit_installment, line.cost_component_code)
            ]
            assert line.payment_date == expected_dates[line.id_financing_credit][
                (line.id_financing_credit_installment, line.cost_component_code)
            ]
        assert all(line.budget_date.year == simulation.budget_year
                   for line in simulation.lines)
        assert all(line.amount > 0 for line in simulation.lines)
        assert simulation.total_annual_expenses == (
            simulation.total_interest + simulation.total_insurance
        )
        assert not any("recalculate" in warning for warning in serialize_credit(session, credit)["warnings"])
        repaired = recalculate_financing_credit(session, credit.id_financing_credit)
        session.commit()
        assert repaired["created_installments"] == 0
        assert repaired["created_budget_lines"] == 0
        assert [row.id_financing_credit_installment for row in installment_query()] == ids_before
        assert session.query(BudgetLine).count() == 0
        session.add(Budget(
            id_budget=1, budget_name="Active", budget_year=2026,
            budget_period="annual", status="active", is_scenario=False,
        ))
        session.commit()
        try:
            planning_financing_simulation(1, session, None)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
        else:
            raise AssertionError("active target simulation must be rejected")
        active_recalc = recalculate_financing_credit(
            session, credit.id_financing_credit,
        )
        session.commit()
        assert active_recalc["created_budget_lines"] == 4
        active_lines = session.query(BudgetLine).all()
        assert len(active_lines) == 4
        assert {line.id_budget for line in active_lines} == {1}
    finally:
        session.close()
        engine.dispose()


def test_budget_principal_flow_is_read_only_and_includes_out_of_year_payments():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models.budget import (
        Budget, BudgetLine, CostCenter, FinancingCredit,
        FinancingCreditInstallment,
    )
    from app.api.budget.planning import planning_financing_principal_flow

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(CostCenter(
            id_cost_center=1, cost_center_code="FIN-PRINCIPAL-FLOW",
            cost_center_name="Principal flow smoke",
        ))
        session.add_all([
            Budget(
                id_budget=1, budget_name="Draft principal flow", budget_year=2026,
                budget_period="annual", status="draft", is_scenario=False,
            ),
            Budget(
                id_budget=2, budget_name="Active principal flow", budget_year=2026,
                budget_period="annual", status="active", is_scenario=True,
            ),
            Budget(
                id_budget=3, budget_name="Closed principal flow", budget_year=2026,
                budget_period="annual", status="closed", is_scenario=True,
            ),
            FinancingCredit(
                id_financing_credit=1, name="Principal loan", lender_name="Flow bank",
                status="active", origin_type="legacy", id_cost_center=1,
                method="french_fixed_payment", currency="COP",
                cutoff_date=date(2025, 11, 30), opening_balance=Decimal("1000.00"),
                annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
                day_count_convention="monthly_periodic", frequency="monthly",
                term_installments=4, first_due_date=date(2025, 12, 30),
                insurance_per_installment=Decimal("0.00"), schedule_revision=2,
            ),
            FinancingCredit(
                id_financing_credit=2, name="Closed loan", lender_name="Closed bank",
                status="closed", origin_type="legacy", id_cost_center=1,
                method="french_fixed_payment", currency="COP",
                cutoff_date=date(2025, 11, 30), opening_balance=Decimal("500.00"),
                annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
                day_count_convention="monthly_periodic", frequency="monthly",
                term_installments=1, first_due_date=date(2026, 1, 30),
                insurance_per_installment=Decimal("0.00"), schedule_revision=1,
                closure_date=date(2025, 12, 1), closure_balance=Decimal("0.00"),
            ),
        ])
        session.flush()

        def installment(credit_id, number, revision, due_date, principal, projection="projected"):
            return FinancingCreditInstallment(
                id_financing_credit=credit_id, installment_number=number,
                period_start=date(due_date.year, due_date.month, 1),
                period_end=due_date, principal_amount=Decimal(principal),
                principal_due_date=due_date, interest_amount=Decimal("10.00"),
                interest_due_date=due_date, insurance_amount=Decimal("5.00"),
                insurance_due_date=due_date, opening_balance=Decimal("1000.00"),
                closing_balance=Decimal("0.00"), rate_used=Decimal("0.120000"),
                rate_convention="nominal_annual", day_count_convention="monthly_periodic",
                method="french_fixed_payment", id_cost_center=1,
                schedule_revision=revision, projection_status=projection,
            )

        session.add_all([
            # Obsolete revision must not duplicate current principal.
            installment(1, 1, 1, date(2025, 12, 30), "900.00"),
            installment(1, 1, 2, date(2025, 12, 30), "100.00"),
            installment(1, 2, 2, date(2026, 4, 15), "200.00"),
            installment(1, 3, 2, date(2027, 1, 5), "300.00"),
            installment(1, 4, 2, date(2026, 6, 15), "500.00", "suspended"),
            installment(1, 5, 2, date(2026, 7, 15), "0.00"),
            installment(2, 1, 1, date(2026, 4, 15), "400.00"),
        ])
        session.commit()

        before = (
            session.query(FinancingCredit).count(),
            session.query(FinancingCreditInstallment).count(),
            session.query(BudgetLine).count(),
        )
        for budget_id in (1, 2, 3):
            response = planning_financing_principal_flow(budget_id, session, None)
            assert response.id_budget == budget_id
            assert response.budget_year == 2026
            assert response.total_principal == Decimal("600.00")
            assert [line.payment_date for line in response.lines] == [
                date(2025, 12, 30), date(2026, 4, 15), date(2027, 1, 5),
            ]
            assert [line.month for line in response.lines] == [
                "2025-12", "2026-04", "2027-01",
            ]
            assert [line.amount for line in response.lines] == [
                Decimal("100.00"), Decimal("200.00"), Decimal("300.00"),
            ]
            assert all(line.id_financing_credit == 1 for line in response.lines)
            assert all(line.id_cost_center == 1 for line in response.lines)
            assert not hasattr(response.lines[0], "interest_amount")
            assert not hasattr(response.lines[0], "insurance_amount")

        after = (
            session.query(FinancingCredit).count(),
            session.query(FinancingCreditInstallment).count(),
            session.query(BudgetLine).count(),
        )
        assert after == before
        assert before[2] == 0
    finally:
        session.close()
        engine.dispose()


def test_set_target_hook_materializes_active_scenario_idempotently():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models.budget import Budget, BudgetLine, CostCenter
    from app.schemas.budget.financingCredit import FinancingCreditCreate
    from app.services.budget.financingCreditService import create_financing_credit
    from app.api.budget.planning import planning_set_target

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all([
            CostCenter(id_cost_center=1, cost_center_code="FIN-ACTIVE-SCENARIO",
                       cost_center_name="Financing active scenario"),
            Budget(id_budget=1, budget_name="Scenario target", budget_year=2026,
                   budget_period="annual", status="draft", is_scenario=True),
        ])
        session.commit()
        payload = FinancingCreditCreate(
            name="Activation loan", lender_name="Smoke bank", origin_type="new",
            id_cost_center=1, method="french_fixed_payment",
            disbursement_date=date(2026, 1, 31),
            original_principal=Decimal("100000.00"),
            opening_balance=Decimal("100000.00"),
            annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
            term_installments=2, insurance_per_installment=Decimal("100.00"),
        )
        credit, _generation = create_financing_credit(session, payload)
        session.commit()
        assert session.query(BudgetLine).count() == 0

        activated = planning_set_target(1, session, current_user=None)
        assert activated["id_budget"] == 1
        assert activated["financing_lines_created"] == 4
        assert activated["financing_warnings"] == []
        assert session.query(Budget).filter_by(id_budget=1).one().status == "active"
        assert session.query(BudgetLine).count() == 4
        assert {line.id_budget for line in session.query(BudgetLine).all()} == {1}

        repeated = planning_set_target(1, session, current_user=None)
        assert repeated["financing_lines_created"] == 0
        assert session.query(BudgetLine).count() == 4
    finally:
        session.close()
        engine.dispose()


def test_legacy_credit_requires_explicit_next_due_date():
    from pydantic import ValidationError

    from app.schemas.budget.financingCredit import FinancingCreditCreate

    common = dict(
        name="Legacy loan", lender_name="Legacy bank", origin_type="legacy",
        id_cost_center=1, method="german_fixed_principal", cutoff_date=date(2026, 1, 15),
        opening_balance=Decimal("100000.00"), annual_rate=Decimal("0.12"),
        rate_convention="nominal_annual", term_installments=2,
        insurance_per_installment=Decimal("0.00"),
    )
    try:
        FinancingCreditCreate(**common)
    except ValidationError as exc:
        assert "first_due_date" in str(exc)
    else:
        raise AssertionError("legacy credits must provide an explicit next due date")

    try:
        FinancingCreditCreate(**common, first_due_date=date(2026, 1, 15))
    except ValidationError as exc:
        assert "after cutoff_date" in str(exc)
    else:
        raise AssertionError("legacy first_due_date must be after cutoff_date")


def test_cashflow_uses_active_schedule_once_independent_of_outflow_source():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.models.budget import (
        Budget, BudgetLine, CostCenter, FinancingCredit,
        FinancingCreditInstallment,
    )
    from app.models.budget.budgetLine import BehaviorTypeEnum, LineTypeEnum
    from app.services.budgetEngine import BudgetEngine

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all([
            CostCenter(id_cost_center=1, cost_center_code="CF-SMOKE",
                       cost_center_name="Cashflow smoke"),
            Budget(id_budget=1, budget_name="Base", budget_year=2026,
                   budget_period="annual", status="active", is_scenario=False),
            Budget(id_budget=2, budget_name="Scenario", budget_year=2026,
                   budget_period="annual", status="active", is_scenario=True),
            FinancingCredit(
                id_financing_credit=1, name="Loan", lender_name="Bank",
                status="active", origin_type="legacy", id_cost_center=1,
                method="french_fixed_payment", currency="COP",
                cutoff_date=date(2026, 1, 1), opening_balance=Decimal("1000000"),
                annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
                day_count_convention="monthly_periodic", frequency="monthly",
                term_installments=1, first_due_date=date(2026, 2, 3),
                insurance_per_installment=Decimal("20000"), schedule_revision=2,
            ),
        ])
        session.flush()
        # Obsolete revision is intentionally larger and must not enter cashflow.
        for revision, amount in ((1, Decimal("5000000")), (2, Decimal("900000"))):
            session.add(FinancingCreditInstallment(
                id_financing_credit=1, installment_number=1,
                period_start=date(2026, 1, 1), period_end=date(2026, 2, 3),
                principal_amount=amount, principal_due_date=date(2026, 2, 3),
                interest_amount=Decimal("80000"), interest_due_date=date(2026, 2, 4),
                insurance_amount=Decimal("20000"), insurance_due_date=date(2026, 2, 5),
                opening_balance=Decimal("1000000"), closing_balance=Decimal("0"),
                rate_used=Decimal("0.120000"), rate_convention="nominal_annual",
                day_count_convention="monthly_periodic",
                method="french_fixed_payment", id_cost_center=1,
                schedule_revision=revision,
            ))
        session.add_all([
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 4),
                projected_amount=Decimal("80000"), source_engine="financing_credit",
                source_engine_id=2, cost_component_code="FIN_INTEREST",
            ),
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 5),
                projected_amount=Decimal("20000"), source_engine="financing_credit",
                source_engine_id=2, cost_component_code="FIN_INSURANCE",
            ),
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 6),
                projected_amount=Decimal("100"), source_engine=None,
            ),
        ])
        session.commit()
        engine_service = BudgetEngine(session)

        def project(source, budget_id=None):
            return engine_service.get_cash_flow(
                date(2026, 2, 1), date(2026, 2, 8), granularity="daily",
                id_budget=budget_id, initial_balance=0, outflow_source=source,
                cutoff_date=date(2026, 2, 1),
            )

        by_budget = project("budget")
        by_ap = project("ap")
        by_scenario = project("budget", 2)
        budget_days = {point["period"]: point["outflows"]
                       for point in by_budget["time_series"]}
        assert budget_days["2026-02-03"] == -900000.0
        assert budget_days["2026-02-04"] == -80000.0
        assert budget_days["2026-02-05"] == -20000.0
        assert budget_days["2026-02-06"] == -100.0
        assert sum(point["outflows"] for point in by_ap["time_series"]) == -1000000.0
        assert sum(point["outflows"] for point in by_scenario["time_series"]) == -1000000.0
        assert by_budget["meta"]["financing_installment_count"] == 1
        assert by_budget["meta"]["financing_principal"] == 900000
        assert by_budget["meta"]["financing_interest"] == 80000
        assert by_budget["meta"]["financing_insurance"] == 20000
    finally:
        session.close()
        engine.dispose()


def test_delete_financing_credit_removes_owned_history_atomically():
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.budget.financingCredit import _commit_or_rollback
    from app.db import Base
    from app.models.budget import (
        Budget, BudgetLine, CostCenter, FinancingCredit,
        FinancingCreditInstallment,
    )
    from app.models.budget.budgetLine import BehaviorTypeEnum, LineTypeEnum
    from app.schemas.budget.financingCredit import FinancingCreditCreate
    from app.services.budget.financingCreditService import (
        close_financing_credit, create_financing_credit,
        delete_financing_credit, update_financing_credit,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add_all([
            CostCenter(
                id_cost_center=1, cost_center_code="FIN-DELETE",
                cost_center_name="Financing delete smoke",
            ),
            Budget(
                id_budget=1, budget_name="Delete target A", budget_year=2026,
                budget_period="annual", status="active", is_scenario=False,
            ),
            Budget(
                id_budget=2, budget_name="Delete target B", budget_year=2026,
                budget_period="annual", status="active", is_scenario=True,
            ),
        ])
        session.commit()

        payload = FinancingCreditCreate(
            name="Credit to delete", lender_name="Delete bank", origin_type="new",
            id_cost_center=1, method="french_fixed_payment",
            disbursement_date=date(2026, 1, 31),
            original_principal=Decimal("100000.00"),
            opening_balance=Decimal("100000.00"),
            annual_rate=Decimal("0.120000"), rate_convention="nominal_annual",
            term_installments=2,
            insurance_per_installment=Decimal("100.00"),
        )
        credit, _created = create_financing_credit(session, payload)
        session.commit()
        old_installments = session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
            schedule_revision=credit.schedule_revision,
        ).all()
        old_ids = [row.id_financing_credit_installment for row in old_installments]
        assert session.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(old_ids),
        ).count() == 8

        credit, _updated = update_financing_credit(
            session, credit.id_financing_credit,
            {"insurance_per_installment": Decimal("200.00")},
        )
        session.commit()
        all_installments = session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
        ).all()
        current_ids = [
            row.id_financing_credit_installment for row in all_installments
            if row.schedule_revision == credit.schedule_revision
        ]
        assert len(all_installments) == 4 and len(old_ids) == 2 and len(current_ids) == 2

        # Simulate an inconsistent but valid historical materialization on both
        # budgets; deletion must include every revision and every budget.
        for budget_id in (1, 2):
            for installment_id in old_ids:
                session.add(BudgetLine(
                    id_budget=budget_id, id_cost_center=1,
                    line_type=LineTypeEnum.EXPENSE,
                    behavior_type=BehaviorTypeEnum.FIXED,
                    budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 1),
                    projected_amount=Decimal("5.00"),
                    source_engine="financing_credit",
                    source_engine_id=installment_id,
                    cost_component_code="FIN_INTEREST",
                    description="historical revision projection",
                ))
        # These rows deliberately share source IDs with the target credit but
        # have different owners/engines and must survive.
        session.add_all([
            BudgetLine(
                id_budget=1, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 1),
                projected_amount=Decimal("33.00"), source_engine=None,
                source_engine_id=current_ids[0], description="manual preserve",
            ),
            BudgetLine(
                id_budget=2, id_cost_center=1, line_type=LineTypeEnum.EXPENSE,
                behavior_type=BehaviorTypeEnum.FIXED,
                budget_date=date(2026, 2, 1), payment_date=date(2026, 2, 1),
                projected_amount=Decimal("44.00"), source_engine="other_engine",
                source_engine_id=current_ids[0], description="other engine preserve",
            ),
        ])

        # A separate closed credit also exercises the same permanent-delete
        # behavior without conflating close (which only suspends a schedule).
        closed_credit, _closed_created = create_financing_credit(
            session, payload.model_copy(update={"name": "Closed then deleted"}),
        )
        close_financing_credit(
            session, closed_credit.id_financing_credit, date.today(), Decimal("0.00"),
        )
        other_credit, _other_created = create_financing_credit(
            session, payload.model_copy(update={"name": "Unrelated active credit"}),
        )
        session.commit()
        closed_installments = session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=closed_credit.id_financing_credit,
        ).count()
        other_installments = session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=other_credit.id_financing_credit,
        ).all()
        other_ids = [row.id_financing_credit_installment for row in other_installments]
        assert len(other_ids) == 2
        assert session.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(other_ids),
        ).count() == 8
        assert closed_credit.status == "closed" and closed_installments == 2

        # Force a failure after owned budget lines have been flushed for delete;
        # the API transaction wrapper must roll all those writes back.
        real_delete = session.delete

        def fail_parent_delete(instance):
            if isinstance(instance, FinancingCredit) and instance.id_financing_credit == credit.id_financing_credit:
                raise RuntimeError("injected parent-delete failure")
            return real_delete(instance)

        session.delete = fail_parent_delete
        try:
            _commit_or_rollback(
                session,
                lambda: delete_financing_credit(session, credit.id_financing_credit),
            )
        except RuntimeError as exc:
            assert "injected" in str(exc)
        else:
            raise AssertionError("forced persistence failure should roll back")
        finally:
            session.delete = real_delete

        assert session.query(FinancingCredit).filter_by(
            id_financing_credit=credit.id_financing_credit,
        ).count() == 1
        assert session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
        ).count() == 4
        assert session.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(old_ids + current_ids),
        ).count() == 12

        deleted = _commit_or_rollback(
            session,
            lambda: delete_financing_credit(session, credit.id_financing_credit),
        )
        assert deleted == {
            "id_financing_credit": credit.id_financing_credit,
            "budget_lines": 12,
            "installments": 4,
        }
        assert session.query(FinancingCredit).filter_by(
            id_financing_credit=credit.id_financing_credit,
        ).count() == 0
        assert session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=credit.id_financing_credit,
        ).count() == 0
        assert session.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(old_ids + current_ids),
        ).count() == 0
        assert {line.description for line in session.query(BudgetLine).filter(
            BudgetLine.source_engine.is_distinct_from("financing_credit"),
        ).all()} == {"manual preserve", "other engine preserve"}

        # Other credits' financing artifacts and closed schedules are untouched
        # by deleting this credit, then can be independently deleted themselves.
        assert session.query(FinancingCredit).filter_by(
            id_financing_credit=closed_credit.id_financing_credit,
        ).one().status == "closed"
        assert session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=closed_credit.id_financing_credit,
        ).count() == closed_installments
        assert session.query(FinancingCredit).filter_by(
            id_financing_credit=other_credit.id_financing_credit,
        ).count() == 1
        assert session.query(FinancingCreditInstallment).filter_by(
            id_financing_credit=other_credit.id_financing_credit,
        ).count() == 2
        assert session.query(BudgetLine).filter(
            BudgetLine.source_engine == "financing_credit",
            BudgetLine.source_engine_id.in_(other_ids),
        ).count() == 8
        closed_deleted = delete_financing_credit(session, closed_credit.id_financing_credit)
        session.commit()
        assert closed_deleted["installments"] == closed_installments

        try:
            delete_financing_credit(session, credit.id_financing_credit)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("a second delete must return HTTP 404")

        from app.api.budget import budget as budget_router

        registered = [
            route for route in budget_router.routes
            if getattr(route, "path", None) is not None
        ]
        delete_route = next(
            route for route in registered
            if route.path == "/budget/financing-credit/{id_financing_credit}"
            and "DELETE" in route.methods
        )
        assert delete_route is not None
        assert any(
            route.path == "/budget/financing-credit/{id_financing_credit}/schedule"
            and "GET" in route.methods
            for route in registered
        )
        legacy_index = next(
            index for index, route in enumerate(registered)
            if route.path == "/budget/{id_budget}"
        )
        assert registered.index(delete_route) < legacy_index
    finally:
        session.close()
        engine.dispose()


class FinancingCreditEngineSmokeTests(unittest.TestCase):
    """Expose the smoke functions to stdlib unittest (pytest is optional)."""

    def test_zero_rate_french_and_german_reconcile_principal(self):
        test_zero_rate_french_and_german_reconcile_principal()

    def test_french_payment_and_german_principal_characteristics(self):
        test_french_payment_and_german_principal_characteristics()

    def test_month_end_schedule_preserves_preferred_day_and_is_future_only(self):
        test_month_end_schedule_preserves_preferred_day_and_is_future_only()

    def test_rate_convention_is_explicit_and_unsupported_day_count_rejected(self):
        test_rate_convention_is_explicit_and_unsupported_day_count_rejected()

    def test_legacy_first_due_on_or_before_cutoff_fails_without_schedule(self):
        test_legacy_first_due_on_or_before_cutoff_fails_without_schedule()

    def test_create_materializes_finance_expenses_and_recalculate_is_idempotent(self):
        test_create_materializes_only_finance_expenses_and_recalculate_is_idempotent()

    def test_draft_budget_simulation_is_read_only(self):
        test_draft_budget_uses_read_only_simulation_not_materialization()

    def test_budget_principal_flow_is_read_only_with_out_of_year_dates(self):
        test_budget_principal_flow_is_read_only_and_includes_out_of_year_payments()

    def test_set_target_hook_materializes_active_scenario_idempotently(self):
        test_set_target_hook_materializes_active_scenario_idempotently()

    def test_legacy_credit_requires_explicit_next_due_date(self):
        test_legacy_credit_requires_explicit_next_due_date()

    def test_cashflow_schedule_is_once_and_independent_of_outflow_source(self):
        test_cashflow_uses_active_schedule_once_independent_of_outflow_source()

    def test_delete_credit_removes_owned_revisions_atomically(self):
        test_delete_financing_credit_removes_owned_history_atomically()
