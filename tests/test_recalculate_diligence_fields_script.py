import importlib
import io
import sys
import unittest
from datetime import date
from types import ModuleType
from unittest.mock import patch


class RecalculateDiligenceFieldsScriptTest(unittest.TestCase):
    def _load_module(self):
        sys.modules.pop("recalculate_diligence_fields", None)
        calls = {"init_db": 0, "recalc": None}

        fake_db = ModuleType("db")

        def init_db():
            calls["init_db"] += 1

        fake_db.init_db = init_db

        fake_repo = ModuleType("email_repository")

        def recalculate_diligence_fields(start_date=None, end_date=None):
            calls["recalc"] = (start_date, end_date)
            return {"scanned": 3, "updated": 3}

        fake_repo.recalculate_diligence_fields = recalculate_diligence_fields

        with patch.dict(sys.modules, {"db": fake_db, "email_repository": fake_repo}):
            module = importlib.import_module("recalculate_diligence_fields")

        return module, calls

    def test_main_parses_date_range_and_runs_backfill(self):
        module, calls = self._load_module()
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            exit_code = module.main(
                ["--start-date", "2026-02-01", "--end-date", "2026-02-28"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["init_db"], 1)
        self.assertEqual(calls["recalc"], (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertIn("3 条记录", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
