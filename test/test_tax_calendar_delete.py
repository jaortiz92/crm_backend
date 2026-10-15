"""Focused tests for tax calendar period deletion."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.budget.taxPlanning import delete_calendar
from app.crud.budget.taxPlanning import delete_tax_calendar


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_args):
        return self

    def first(self):
        return self.value


class _Session:
    def __init__(self, period=None, commit_error=None):
        self.period = period
        self.commit_error = commit_error
        self.deleted = []
        self.rollback_count = 0

    def query(self, _model):
        return _Query(self.period)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollback_count += 1


class TaxCalendarDeleteTests(unittest.TestCase):
    def test_crud_deletes_existing_period(self):
        period = SimpleNamespace(id_tax_calendar_period=7)
        db = _Session(period)

        result = delete_tax_calendar(db, 7)

        self.assertIs(result, period)
        self.assertEqual(db.deleted, [period])
        self.assertEqual(db.rollback_count, 0)

    def test_crud_rolls_back_when_commit_fails(self):
        period = SimpleNamespace(id_tax_calendar_period=7)
        db = _Session(period, RuntimeError("commit failed"))

        with self.assertRaises(RuntimeError):
            delete_tax_calendar(db, 7)

        self.assertEqual(db.rollback_count, 1)

    def test_endpoint_returns_message_and_id(self):
        db = _Session()
        user = SimpleNamespace(
            role=SimpleNamespace(role_name="admin", access_type="")
        )
        period = SimpleNamespace(id_tax_calendar_period=7)

        with patch("app.api.budget.taxPlanning.crud.delete_tax_calendar", return_value=period):
            result = delete_calendar(7, db, user)

        self.assertEqual(
            result,
            {
                "message": "Tax calendar period deleted successfully",
                "deleted_id": 7,
            },
        )

    def test_endpoint_maps_missing_period_to_404(self):
        db = _Session()
        user = SimpleNamespace(
            role=SimpleNamespace(role_name="admin", access_type="")
        )

        with patch("app.api.budget.taxPlanning.crud.delete_tax_calendar", return_value=None):
            with self.assertRaises(HTTPException) as context:
                delete_calendar(7, db, user)

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(db.rollback_count, 1)


if __name__ == "__main__":
    unittest.main()
