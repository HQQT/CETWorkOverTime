import importlib
import io
import json
import logging
import sys
import tempfile
import threading
import types
import unittest
from datetime import time
from pathlib import Path
from unittest.mock import patch
import zipfile


class _FakeJsonResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def get_json(self):
        return self._payload


class _FakeRequest:
    def __init__(self):
        self.endpoint = None
        self.path = "/"
        self.args = {}
        self._json = {}

    def get_json(self, silent=False):
        return self._json


class _FakeTimer:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        return None

    def cancel(self):
        return None


def _build_fake_flask_module():
    fake_flask = types.ModuleType("flask")
    fake_flask.request = _FakeRequest()
    fake_flask.session = {"logged_in": True}

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            self.secret_key = None

        def route(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def before_request(self, func):
            return func

        def errorhandler(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    def jsonify(payload):
        json.dumps(payload, ensure_ascii=False)
        return _FakeJsonResponse(payload)

    fake_flask.Flask = FakeFlask
    fake_flask.jsonify = jsonify
    fake_flask.render_template = lambda template_name: template_name
    fake_flask.abort = lambda code, description=None: (_ for _ in ()).throw(
        RuntimeError(description or f"abort {code}")
    )
    fake_flask.redirect = lambda url: _FakeJsonResponse({"redirect": url}, status_code=302)
    fake_flask.url_for = lambda name: f"/{name}"
    return fake_flask


def _load_app_module():
    sys.modules.pop("app", None)

    fake_flask = _build_fake_flask_module()
    fake_db = types.ModuleType("db")

    class DatabaseDependencyError(Exception):
        pass

    fake_db.DatabaseDependencyError = DatabaseDependencyError
    fake_db.init_db = lambda: None

    fake_repo = types.ModuleType("email_repository")
    fake_repo.get_emails_by_month = lambda year, month: [
        {
            "email_date": "2026-02-03",
            "subject": "工作日志",
            "diligence_hours": 9.5,
            "diligence_start": time(9, 30),
            "diligence_end": time(19, 0),
            "content": "完成日报",
        }
    ]
    fake_repo.get_all_years = lambda: [2026]
    fake_repo.get_diligence_stats = lambda year: {
        "year": year,
        "months": [
            {
                "month": 2,
                "entries": 20,
                "hours": 180.5,
                "target": 36,
                "delta": 144.5,
            }
        ],
        "total_hours": 180.5,
        "total_target": 36,
        "total_delta": 144.5,
    }

    fake_fetcher = types.ModuleType("email_fetcher")
    fake_processor = types.ModuleType("email_processor")

    class EmailFetcher:
        def __init__(self, *args, **kwargs):
            pass

    class EmailProcessor:
        def __init__(self, *args, **kwargs):
            pass

    fake_fetcher.EmailFetcher = EmailFetcher
    fake_processor.EmailProcessor = EmailProcessor

    with patch.object(threading, "Timer", _FakeTimer), \
         patch.object(logging, "FileHandler", return_value=logging.NullHandler()), \
         patch.dict(
             "sys.modules",
             {
                 "flask": fake_flask,
                 "db": fake_db,
                 "email_repository": fake_repo,
                 "email_fetcher": fake_fetcher,
                 "email_processor": fake_processor,
             },
         ):
        return importlib.import_module("app")


class DashboardReportContractTest(unittest.TestCase):
    def test_api_month_diligence_returns_json_safe_time_strings(self):
        app_module = _load_app_module()

        response = app_module.api_month_diligence(2026, 2)
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["days"][0]["start"], "09:30")
        self.assertEqual(payload["days"][0]["end"], "19:00")
        self.assertEqual(payload["days"][0]["hours"], 9.5)

    def test_api_reports_keeps_database_entries_and_hours_contract(self):
        app_module = _load_app_module()

        response = app_module.api_reports()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["reports"],
            [
                {
                    "filename": "2026年02月工作总结.md",
                    "entries": 20,
                    "hours": 180.5,
                    "source": "database",
                }
            ],
        )

    def test_api_diligence_file_fallback_uses_normalized_half_hour_rule(self):
        app_module = _load_app_module()
        app_module._db_available = False

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir)
            (report_dir / "2026年02月工作总结.md").write_text(
                "\n".join(
                    [
                        "[勤奋时间][17:45][18:10]",
                        "[勤奋时间][17:45][19:30]",
                    ]
                ),
                encoding="utf-8",
            )
            app_module.config.OUTPUT_DIR = report_dir

            response = app_module.api_diligence()
            payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["source"], "file")
        self.assertEqual(payload["years"]["2026"]["months"][0]["hours"], 1.5)
        self.assertEqual(payload["years"]["2026"]["months"][0]["entries"], 1)

    def test_api_reports_download_returns_zip_for_selected_reports(self):
        app_module = _load_app_module()
        app_module.request._json = {
            "filenames": ["2026年02月工作总结.md", "2026年02月工作总结.md"]
        }

        body, status_code, headers = app_module.api_reports_download()

        self.assertEqual(status_code, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertIn("attachment; filename=", headers["Content-Disposition"])

        with zipfile.ZipFile(io.BytesIO(body), "r") as archive:
            self.assertEqual(archive.namelist(), ["2026年02月工作总结.md"])
            content = archive.read("2026年02月工作总结.md").decode("utf-8")

        self.assertIn("# 2026年02月工作总结", content)
        self.assertIn("**主题**: 工作日志", content)

    def test_api_reports_download_rejects_empty_selection(self):
        app_module = _load_app_module()
        app_module.request._json = {"filenames": []}

        response, status_code = app_module.api_reports_download()
        payload = response.get_json()

        self.assertEqual(status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("至少选择一份报告", payload["error"])

    def test_api_reports_download_rejects_invalid_or_missing_reports(self):
        app_module = _load_app_module()
        app_module.request._json = {"filenames": ["../2026年02月工作总结.md"]}

        response, status_code = app_module.api_reports_download()
        payload = response.get_json()

        self.assertEqual(status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("非法", payload["error"])

    def test_api_reports_download_rejects_reports_not_present_in_list(self):
        app_module = _load_app_module()
        app_module.request._json = {"filenames": ["2099年01月工作总结.md"]}

        response, status_code = app_module.api_reports_download()
        payload = response.get_json()

        self.assertEqual(status_code, 404)
        self.assertFalse(payload["ok"])
        self.assertIn("报告不存在", payload["error"])

    def test_reports_template_uses_source_aware_metadata_and_safe_size_fallback(self):
        template = Path("templates/index.html").read_text(encoding="utf-8")

        self.assertIn("function formatReportMeta(report)", template)
        self.assertIn("report.source === 'database'", template)
        self.assertIn("未知大小", template)
        self.assertIn("selectedReports", template)
        self.assertIn("downloadSelectedReports", template)
        self.assertIn("toggleSelectAllReports", template)
        self.assertIn('data-filename="${encodeURIComponent(report.filename)}"', template)
        self.assertIn("function attachReportListHandlers()", template)


if __name__ == "__main__":
    unittest.main()
