import unittest
from datetime import date

import diligence_time


class DiligenceTimeRuleTest(unittest.TestCase):
    def test_normalizes_to_half_hour_slots_from_actual_start_time(self):
        result = diligence_time.normalize_diligence_window("18:10", "19:30")

        self.assertEqual(result["start"], "18:10")
        self.assertEqual(result["end"], "19:10")
        self.assertEqual(result["minutes"], 60)
        self.assertEqual(result["hours"], 1.0)

    def test_keeps_boundary_end_time_unchanged(self):
        result = diligence_time.normalize_diligence_window("09:10", "11:40")

        self.assertEqual(result["start"], "09:10")
        self.assertEqual(result["end"], "11:40")
        self.assertEqual(result["hours"], 2.5)

    def test_discards_partial_half_hour_credit(self):
        result = diligence_time.normalize_diligence_window("18:10", "18:35")

        self.assertEqual(result["minutes"], 0)
        self.assertEqual(result["hours"], 0.0)
        self.assertIsNone(result["start"])
        self.assertIsNone(result["end"])

    def test_date_context_does_not_change_start_time_baseline(self):
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
        result = diligence_time.normalize_diligence_window("18:10", "00:20")

        self.assertEqual(result["start"], "18:10")
        self.assertEqual(result["end"], "00:10")
        self.assertEqual(result["minutes"], 360)
        self.assertEqual(result["hours"], 6.0)

    def test_extract_last_diligence_record_ignores_invalid_or_missing_entries(self):
        self.assertEqual(diligence_time.extract_last_diligence_record("没有勤奋时间"), {})
        self.assertEqual(
            diligence_time.extract_last_diligence_record("[勤奋时间][bad][19:30]"),
            {},
        )

    def test_extract_last_diligence_record_uses_last_match(self):
        content = "\n".join(
            [
                "[勤奋时间][18:10][18:20]",
                "[勤奋时间][18:10][19:30]",
            ]
        )

        result = diligence_time.extract_last_diligence_record(content)

        self.assertEqual(
            result,
            {
                "start": "18:10",
                "end": "19:10",
                "hours": 1.0,
                "minutes": 60,
            },
        )

    def test_extract_last_diligence_record_keeps_same_rule_with_date_context(self):
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
                "[勤奋时间][18:10][18:20]",
                "[勤奋时间][18:10][19:30]",
                "[勤奋时间][18:10][20:45]",
            ]
        )

        self.assertEqual(diligence_time.sum_diligence_minutes(content), 210)
        self.assertEqual(diligence_time.sum_diligence_hours(content), 3.5)

    def test_report_content_uses_same_start_based_rule_for_all_dates(self):
        report_content = "\n".join(
            [
                "### 2026年02月06日 (星期五)",
                "",
                "[勤奋时间][18:10][19:30]",
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
                {"start": "18:10", "end": "19:10", "hours": 1.0, "minutes": 60},
                {"start": "09:10", "end": "11:40", "hours": 2.5, "minutes": 150},
            ],
        )
        self.assertEqual(diligence_time.sum_report_diligence_hours(report_content), 3.5)


if __name__ == "__main__":
    unittest.main()
