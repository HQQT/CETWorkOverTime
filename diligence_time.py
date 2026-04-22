"""Shared diligence-time normalization helpers."""

from __future__ import annotations

import re
from typing import Optional

DILIGENCE_PATTERN = re.compile(r"\[勤奋时间\]\[(\d{1,2}:\d{2})\]\[(\d{1,2}:\d{2})\]")
BASE_START_TIME = "17:45"
BASE_START_MINUTES = 17 * 60 + 45
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


def normalize_diligence_window(start_time: str, end_time: str) -> dict:
    """
    Normalize diligence time against the fixed 17:45 baseline.

    Credited time is counted in 30-minute slots only, rounding the end time
    down to the last reachable slot from the 17:45 baseline.
    """
    start_minutes = parse_time(start_time)
    end_minutes = parse_time(end_time)
    if start_minutes is None or end_minutes is None:
        return empty_diligence_result()

    if end_minutes < start_minutes:
        end_minutes += 24 * 60

    elapsed_from_baseline = end_minutes - BASE_START_MINUTES
    if elapsed_from_baseline < HALF_HOUR_MINUTES:
        return empty_diligence_result()

    credited_minutes = (elapsed_from_baseline // HALF_HOUR_MINUTES) * HALF_HOUR_MINUTES
    effective_end_minutes = BASE_START_MINUTES + credited_minutes

    return {
        "start": BASE_START_TIME,
        "end": format_time(effective_end_minutes),
        "hours": round(credited_minutes / 60.0, 2),
        "minutes": int(credited_minutes),
    }


def extract_diligence_ranges(content: str) -> list[tuple[str, str]]:
    """Extract all diligence ranges from content."""
    return DILIGENCE_PATTERN.findall(content or "")


def extract_normalized_diligence_records(content: str) -> list[dict]:
    """Extract and normalize all credited diligence records from content."""
    records = []
    for start_time, end_time in extract_diligence_ranges(content):
        record = normalize_diligence_window(start_time, end_time)
        if record["minutes"] > 0:
            records.append(record)
    return records


def extract_last_diligence_record(content: str) -> dict:
    """Extract and normalize the last diligence record in content."""
    matches = extract_diligence_ranges(content)
    if not matches:
        return {}

    record = normalize_diligence_window(*matches[-1])
    if record["minutes"] <= 0:
        return {}
    return record


def sum_diligence_minutes(content: str) -> int:
    """Sum all credited diligence minutes in content."""
    return sum(record["minutes"] for record in extract_normalized_diligence_records(content))


def sum_diligence_hours(content: str) -> float:
    """Sum all credited diligence hours in content."""
    return round(sum_diligence_minutes(content) / 60.0, 2)
