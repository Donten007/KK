"""客户跟进催办纯逻辑层单测（解析三分 / 超期边界 / 阈值校验 / 溯源引用）。

超期判定口径：「超过 N 天未跟进」按字面语义 = 严格大于 N。
恰好第 N 天不算超期 —— 少打扰一天的成本远低于误催一次的信任成本。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.jobs.followup_script import (
    FollowupRecord,
    NoopScriptWriter,
    is_overdue,
    is_valid_threshold,
    parse_followup_records,
)

TODAY = date(2026, 10, 15)


def _record(days_ago: int | None, customer: str = "深圳华创") -> FollowupRecord:
    last = (
        datetime.now(UTC).date() - timedelta(days=days_ago)
        if days_ago is not None
        else None
    )
    return FollowupRecord(row_no=2, customer=customer, last_followup_date=last, note="")


# ---- 超期识别边界 ----


def test_exactly_threshold_days_is_not_overdue() -> None:
    assert not is_overdue(_record(7), TODAY, threshold_days=7)


def test_one_day_past_threshold_is_overdue() -> None:
    assert is_overdue(_record(8), TODAY, threshold_days=7)


def test_recent_record_is_not_overdue() -> None:
    assert not is_overdue(_record(1), TODAY, threshold_days=7)


def test_missing_date_never_counts_as_overdue() -> None:
    # 拿不准 ≠ 超期：日期缺失的记录不允许被当成超期催办
    assert not is_overdue(_record(None), TODAY, threshold_days=7)


# ---- 解析三分 ----


def test_parse_splits_valid_uncertain_unusable() -> None:
    rows: list[Any] = [
        {"row": 2, "customer": "客户A", "last_followup_date": "2026-10-01", "note": "等回复"},
        {"row": 3, "customer": "客户B", "last_followup_date": None, "note": "日期没填"},
        {"row": 4, "customer": "客户C", "last_followup_date": "10月32日", "note": "日期是坏的"},
        {"row": 5, "customer": "", "last_followup_date": "2026-10-01", "note": "没客户名"},
    ]
    result = parse_followup_records(rows)
    assert [r.customer for r in result.valid] == ["客户A"]
    assert [r.customer for r in result.uncertain] == ["客户B", "客户C"]
    assert result.uncertain[1].row_no == 4, "日期填坏也要保住来源行号（溯源）"
    assert [r.row_no for r in result.unusable] == [5]


def test_parse_accepts_common_date_formats() -> None:
    rows = [
        {"row": 2, "customer": "A", "last_followup_date": "2026/10/01", "note": ""},
        {"row": 3, "customer": "B", "last_followup_date": "2026年10月2日", "note": ""},
        {"row": 4, "customer": "C", "last_followup_date": "2026-10-03 14:30", "note": ""},
    ]
    result = parse_followup_records(rows)
    assert len(result.valid) == 3
    assert result.valid[2].last_followup_date == date(2026, 10, 3)


def test_parse_assigns_row_number_when_missing() -> None:
    result = parse_followup_records([{"customer": "A", "last_followup_date": "2026-10-01", "note": ""}])
    assert result.valid[0].row_no == 2, "无显式行号时按枚举序号（含表头）"


# ---- 阈值校验 ----


def test_threshold_validation_rejects_bad_values() -> None:
    for bad in (0, -1, 366, True, False, "7", 7.0, None):
        assert not is_valid_threshold(bad), f"{bad!r} 不应通过校验"
    assert is_valid_threshold(7)
    assert is_valid_threshold(1) and is_valid_threshold(365)


# ---- 话术兜底：只用真实事实 ----


async def test_noop_writer_uses_only_record_facts() -> None:
    record = FollowupRecord(
        row_no=5, customer="深圳华创", last_followup_date=date(2026, 9, 30),
        note="报价后等回复",
    )
    script = await NoopScriptWriter().draft(record, overdue_days=15)
    assert "深圳华创" in script and "15" in script and "2026-09-30" in script
    assert "报价后等回复" in script


# ---- 溯源引用 ----


def test_citation_references_source_row() -> None:
    record = FollowupRecord(row_no=5, customer="A", last_followup_date=None, note="")
    assert record.citation() == "input#row:5"
    assert record.citation("0c0ffee0-0000-0000-0000-000000000000") == (
        "asset:0c0ffee0-0000-0000-0000-000000000000#row:5"
    )
