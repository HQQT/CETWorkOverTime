import importlib
import sys
import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import ModuleType
from unittest.mock import patch


class _FakeCursor:
    def __init__(self, fetchone_results=None, fetchall_results=None):
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class EmailRepositoryPostgresSqlTest(unittest.TestCase):
    def _load_repo(self, cursor):
        fake_db = ModuleType("db")
        fake_db.get_connection = lambda: _FakeConnection(cursor)
        fake_db.get_table_name = lambda year: "emails"
        fake_db.ensure_year_table = lambda year: None
        fake_db.ensure_meta_table = lambda: None

        with patch.dict(sys.modules, {"db": fake_db}):
            sys.modules.pop("email_repository", None)
            return importlib.import_module("email_repository")

    def test_get_emails_by_month_uses_date_range_query(self):
        cursor = _FakeCursor(fetchall_results=[[]])
        repo = self._load_repo(cursor)

        repo.get_emails_by_month(2026, 3)

        sql, params = cursor.executed[0]
        self.assertIn("email_date >= %s", sql)
        self.assertIn("email_date < %s", sql)
        self.assertNotIn("MONTH(email_date)", sql)
        self.assertEqual(params, (date(2026, 3, 1), date(2026, 4, 1)))

    def test_get_all_years_reads_distinct_years_from_single_table(self):
        cursor = _FakeCursor(fetchall_results=[[{"year": 2024}, {"year": 2026}]])
        repo = self._load_repo(cursor)

        years = repo.get_all_years()

        sql, params = cursor.executed[0]
        self.assertIn("FROM emails", sql)
        self.assertIn("EXTRACT(YEAR FROM email_date)", sql)
        self.assertNotIn("INFORMATION_SCHEMA.TABLES", sql)
        self.assertEqual(params, None)
        self.assertEqual(years, [2024, 2026])

    def test_save_meta_uses_postgres_upsert(self):
        cursor = _FakeCursor()
        repo = self._load_repo(cursor)

        repo.save_meta("fetch_cache", '{"last_uid": 1}')

        sql, params = cursor.executed[0]
        self.assertIn("ON CONFLICT (meta_key) DO UPDATE", sql)
        self.assertNotIn("ON DUPLICATE KEY", sql)
        self.assertEqual(params, ("fetch_cache", '{"last_uid": 1}'))

    def test_serialize_row_converts_special_types_to_json_safe_values(self):
        repo = self._load_repo(_FakeCursor())

        result = repo._serialize_row(
            {
                "email_date": date(2026, 2, 3),
                "created_at": datetime(2026, 2, 3, 9, 30, 15),
                "diligence_start": time(9, 30),
                "duration": timedelta(hours=9, minutes=45),
                "hours": Decimal("9.75"),
            }
        )

        self.assertEqual(result["email_date"], "2026-02-03")
        self.assertEqual(result["created_at"], "2026-02-03T09:30:15")
        self.assertEqual(result["diligence_start"], "09:30")
        self.assertEqual(result["duration"], "09:45")
        self.assertEqual(result["hours"], 9.75)

    def test_save_email_normalizes_diligence_fields_to_half_hour_slots(self):
        cursor = _FakeCursor(fetchone_results=[None, {"id": 7}])
        repo = self._load_repo(cursor)

        record_id = repo.save_email(
            email_date=date(2026, 2, 3),
            content="[勤奋时间][17:45][19:30]",
        )

        self.assertEqual(record_id, 7)
        insert_sql, insert_params = cursor.executed[1]
        self.assertIn("INSERT INTO emails", insert_sql)
        self.assertEqual(insert_params[5:8], ("17:45", "19:15", 1.5))

    def test_save_email_uses_actual_weekend_start_time(self):
        cursor = _FakeCursor(fetchone_results=[None, {"id": 9}])
        repo = self._load_repo(cursor)

        record_id = repo.save_email(
            email_date=date(2026, 2, 7),
            content="[勤奋时间][09:10][12:00]",
        )

        self.assertEqual(record_id, 9)
        _, insert_params = cursor.executed[1]
        self.assertEqual(insert_params[5:8], ("09:10", "11:40", 2.5))

    def test_recalculate_diligence_fields_updates_derived_columns_from_content(self):
        cursor = _FakeCursor(
            fetchall_results=[
                [
                    {
                        "id": 10,
                        "email_date": date(2026, 2, 3),
                        "content": "[勤奋时间][17:45][19:30]",
                    },
                    {
                        "id": 11,
                        "email_date": date(2026, 2, 4),
                        "content": "没有勤奋时间",
                    },
                ]
            ]
        )
        repo = self._load_repo(cursor)

        stats = repo.recalculate_diligence_fields(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )

        self.assertEqual(stats, {"scanned": 2, "updated": 2})
        select_sql, select_params = cursor.executed[0]
        self.assertIn("SELECT id, email_date, content FROM emails", select_sql)
        self.assertEqual(select_params, (date(2026, 2, 1), date(2026, 2, 28)))

        first_update_sql, first_update_params = cursor.executed[1]
        second_update_sql, second_update_params = cursor.executed[2]
        self.assertIn("UPDATE emails", first_update_sql)
        self.assertEqual(first_update_params, ("17:45", "19:15", 1.5, 10))
        self.assertEqual(second_update_params, (None, None, 0, 11))


if __name__ == "__main__":
    unittest.main()
