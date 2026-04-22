"""Shared diligence-time normalization helpers."""

from __future__ import annotations

import re
from typing import Optional

DILIGENCE_PATTERN = re.compile(r"\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]")
HALF_HOUR_MINUTES = 30


def parse_time(value: str) -> Optional[int]:
    """Parse HH:MM into minutes since midnight."""
    if not value or ":" not in value:
        return None

    try:
        hours, minutes = map(int, value.split(":", 1))
    except ValueError:
        return None

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def format_time(total_minutes: int) -> str:
    """Format minutes since midnight (possibly next day) back to HH:MM."""
    normalized = total_minutes % (24 * 60)
    hours = normalized // 60
    minutes = normalized % 60
    return f"{hours:02d}:{minutes:02d}"


def empty_diligence_result() -> dict:
    """Return an empty normalized diligence result."""
    return {
        "start": None,
        "end": None,
        "hours": 0.0,
        "minutes": 0,
    }

def normalize_diligence_window(start_time: str, end_time: str, work_date=None) -> dict:
    """
    Normalize diligence time against the email's recorded start time.

    Credited time is counted in 30-minute slots only, rounding the end time
    down to the last reachable slot from the recorded start time.

    The optional work_date argument is kept for compatibility with older call
    sites, but no longer changes the normalization rule.
    """
    start_minutes = parse_time(start_time)
    end_minutes = parse_time(end_time)
    if start_minutes is None or end_minutes is None:
        return empty_diligence_result()

    if end_minutes < start_minutes:
        end_minutes += 24 * 60

    baseline_minutes = start_minutes
    elapsed_from_baseline = end_minutes - baseline_minutes
    if elapsed_from_baseline < HALF_HOUR_MINUTES:
        return empty_diligence_result()

    credited_minutes = (elapsed_from_baseline // HALF_HOUR_MINUTES) * HALF_HOUR_MINUTES
    effective_end_minutes = baseline_minutes + credited_minutes

    return {
        "start": format_time(start_minutes),
        "end": format_time(effective_end_minutes),
        "hours": round(credited_minutes / 60.0, 2),
        "minutes": int(credited_minutes),
    }


def extract_diligence_ranges(content: str) -> list[tuple[str, str]]:
    """Extract all diligence ranges from content."""
    return DILIGENCE_PATTERN.findall(content or "")


def extract_normalized_diligence_records(content: str, work_date=None) -> list[dict]:
    """Extract and normalize all credited diligence records from content."""
    records = []
    for start_time, end_time in extract_diligence_ranges(content):
        record = normalize_diligence_window(start_time, end_time, work_date=work_date)
        if record["minutes"] > 0:
            records.append(record)
    return records


def extract_last_diligence_record(content: str, work_date=None) -> dict:
    """Extract and normalize the last diligence record in content."""
    matches = extract_diligence_ranges(content)
    if not matches:
        return {}

    record = normalize_diligence_window(*matches[-1], work_date=work_date)
    if record["minutes"] <= 0:
        return {}
    return record


def sum_diligence_minutes(content: str, work_date=None) -> int:
    """Sum all credited diligence minutes in content."""
    return sum(
        record["minutes"]
        for record in extract_normalized_diligence_records(content, work_date=work_date)
    )


def sum_diligence_hours(content: str, work_date=None) -> float:
    """Sum all credited diligence hours in content."""
    return round(sum_diligence_minutes(content, work_date=work_date) / 60.0, 2)


def extract_report_diligence_records(report_content: str) -> list[dict]:
    """Extract normalized diligence records from a generated monthly report."""
    return extract_normalized_diligence_records(report_content or "")


def sum_report_diligence_hours(report_content: str) -> float:
    """Sum normalized diligence hours from a generated monthly report."""
    return round(
        sum(record["hours"] for record in extract_report_diligence_records(report_content)),
        2,
    )
