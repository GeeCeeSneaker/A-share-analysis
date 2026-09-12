"""Explicit CR-7 Development / Validation A / Holdout boundaries."""

from __future__ import annotations

from datetime import date

from ashare_state.research.models import (
    ResearchPanelError,
    ResearchSplit,
    parse_date_value,
    split_windows,
)

__all__ = [
    "assign_research_split",
    "assert_research_split_date",
    "split_window",
]


def assign_research_split(value: date | str) -> ResearchSplit:
    """Assign one date without allowing a date to silently cross partitions."""
    trade_date = parse_date_value(value)
    for split, (start, end) in split_windows().items():
        if start <= trade_date <= end:
            return split
    if trade_date < split_windows()[ResearchSplit.DEVELOPMENT][0]:
        return ResearchSplit.WARMUP
    return ResearchSplit.OUTSIDE_WINDOW


def split_window(split: ResearchSplit | str) -> tuple[date, date]:
    try:
        normalized = ResearchSplit(split)
    except ValueError as exc:
        raise ResearchPanelError(f"unknown research split {split!r}") from exc
    try:
        return split_windows()[normalized]
    except KeyError as exc:
        raise ResearchPanelError(f"{normalized.value} is not a readable research split") from exc


def assert_research_split_date(value: date | str, split: ResearchSplit | str) -> date:
    trade_date = parse_date_value(value)
    start, end = split_window(split)
    if not start <= trade_date <= end:
        raise ResearchPanelError(
            f"trade_date {trade_date.isoformat()} is outside {ResearchSplit(split).value}"
        )
    return trade_date
