import unittest
from datetime import date

import diligence_time


class DiligenceTimeRuleTest(unittest.TestCase):
    def test_normalizes_to_half_hour_slots_from_1745(self):
        result = diligence_time.normalize_diligence_window("17:45", "19:30")

        self.assertEqual(result["start"], "17:45")
        self.assertEqual(result["end"], "19:15")
        self.assertEqual(result["minutes"], 90)
        self.assertEqual(result["hours"], 1.5)

    def test_keeps_boundary_end_time_unchanged(self):
        result = diligence_time.normalize_diligence_window("17:45", "19:15")

        self.assertEqual(result["start"], "17:45")
        self.assertEqual(result["end"], "19:15")
        self.assertEqual(result["hours"], 1.5)

    def test_discards_partial_half_hour_credit(self):
        result = diligence_time.normalize_diligence_window("17:45", "18:10")

        self.assertEqual(result["minutes"], 0)
        self.assertEqual(result["hours"], 0.0)
        self.assertIsNone(result["start"])
        self.assertIsNone(result["end"])

    def test_weekend_uses_actual_start_time_as_baseline(self):
        result = diligence_time.normalize_diligence_window(
            "09:10",
            "12:00",
            work_date=date(2026, 2, 7),
        )

        self.assertEqual(result["start"], "09:10")
        self.assertEqual(result["end"], "11:40")
        self.assertEqual(result["minutes"], 150)
        self.assertEqual(result["hours"], 2.5)

    def test_cross_midnight_still_rounds_down(self):
        result = diligence_time.normalize_diligence_window("17:45", "00:20")

        self.assertEqual(result["start"], "17:45")
        self.assertEqual(result["end"], "00:15")
        self.assertEqual(result["minutes"], 390)
        self.assertEqual(result["hours"], 6.5)

    def test_extract_last_diligence_record_ignores_invalid_or_missing_entries(self):
        self.assertEqual(diligence_time.extract_last_diligence_record("没有勤奋时间"), {})
        self.assertEqual(
            diligence_time.extract_last_diligence_record("[勤奋时间][bad][19:30]"),
            {},
        )

    def test_extract_last_diligence_record_uses_last_match(self):
        content = "\n".join(
            [
                "[勤奋时间][17:45][18:10]",
                "[勤奋时间][17:45][19:30]",
            ]
        )

        result = diligence_time.extract_last_diligence_record(content)

        self.assertEqual(
            result,
            {
                "start": "17:45",
                "end": "19:15",
                "hours": 1.5,
                "minutes": 90,
            },
        )

    def test_extract_last_diligence_record_uses_weekend_date_context(self):
        result = diligence_time.extract_last_diligence_record(
            "[勤奋时间][09:10][12:00]",
            work_date=date(2026, 2, 7),
        )

        self.assertEqual(
            result,
            {
                "start": "09:10",
                "end": "11:40",
                "hours": 2.5,
                "minutes": 150,
            },
        )

    def test_sum_diligence_hours_counts_only_full_slots(self):
        content = "\n".join(
            [
                "[勤奋时间][17:45][18:10]",
                "[勤奋时间][17:45][19:30]",
                "[勤奋时间][17:45][20:45]",
            ]
        )

        self.assertEqual(diligence_time.sum_diligence_minutes(content), 270)
        self.assertEqual(diligence_time.sum_diligence_hours(content), 4.5)

    def test_report_content_uses_weekend_date_per_section(self):
        report_content = "\n".join(
            [
                "### 2026年02月06日 (星期五)",
                "",
                "[勤奋时间][17:45][19:30]",
                "",
                "### 2026年02月07日 (星期六)",
                "",
                "[勤奋时间][09:10][12:00]",
            ]
        )

        records = diligence_time.extract_report_diligence_records(report_content)

        self.assertEqual(
            records,
            [
                {"start": "17:45", "end": "19:15", "hours": 1.5, "minutes": 90},
                {"start": "09:10", "end": "11:40", "hours": 2.5, "minutes": 150},
            ],
        )
        self.assertEqual(diligence_time.sum_report_diligence_hours(report_content), 4.0)


if __name__ == "__main__":
    unittest.main()
