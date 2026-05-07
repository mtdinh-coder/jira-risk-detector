"""Tests for risk classification rules."""
from datetime import datetime, timedelta, timezone

from src.config import RiskConfig
from src.models import JiraTicket, RiskCategory
from src.risk_detector import build_jql, detect_risks

NOW = datetime.now(timezone.utc)


def _ticket(**overrides) -> JiraTicket:
    base = dict(
        key="ABC-1",
        url="https://x/browse/ABC-1",
        summary="example",
        status="In Progress",
        priority="High",
        labels=[],
        assignee_name="Alice",
        assignee_email="alice@x.com",
        qa_name=None,
        qa_email=None,
        due_date=None,
        updated=NOW,
    )
    base.update(overrides)
    return JiraTicket(**base)


def _cfg(stalled=3, due_soon=2):
    return RiskConfig(stalled_days=stalled, due_soon_days=due_soon, comments_for_summary=8)


def test_blocked_status_wins_over_stalled():
    t = _ticket(status="Blocked", updated=NOW - timedelta(days=10))
    risks = detect_risks([t], _cfg())
    assert len(risks) == 1
    assert risks[0].category == RiskCategory.BLOCKED


def test_blocker_label_treated_as_blocked():
    t = _ticket(status="In Progress", labels=["blocker"])
    risks = detect_risks([t], _cfg())
    assert risks[0].category == RiskCategory.BLOCKED


def test_overdue_detected_when_due_in_past():
    t = _ticket(status="In Progress", due_date=NOW - timedelta(days=4))
    risks = detect_risks([t], _cfg())
    assert risks[0].category == RiskCategory.OVERDUE
    assert "ago" in risks[0].detail


def test_stalled_when_in_progress_and_old_update():
    t = _ticket(status="In Progress", updated=NOW - timedelta(days=5))
    risks = detect_risks([t], _cfg(stalled=3))
    assert risks[0].category == RiskCategory.STALLED


def test_due_soon_within_threshold():
    t = _ticket(status="In Progress", due_date=NOW + timedelta(days=1))
    risks = detect_risks([t], _cfg())
    assert risks[0].category == RiskCategory.DUE_SOON


def test_recent_in_progress_not_at_risk():
    t = _ticket(status="In Progress", updated=NOW - timedelta(hours=2))
    assert detect_risks([t], _cfg()) == []


def test_done_status_outside_jql_but_still_safe():
    # Even if a Done ticket leaks through, classification rules should not flag it.
    t = _ticket(status="Done", updated=NOW - timedelta(days=30))
    assert detect_risks([t], _cfg()) == []


def test_severity_ordering():
    blocked = _ticket(key="A-1", status="Blocked")
    overdue = _ticket(key="A-2", status="In Progress", due_date=NOW - timedelta(days=1))
    stalled = _ticket(key="A-3", status="In Progress", updated=NOW - timedelta(days=5))
    due_soon = _ticket(key="A-4", status="In Progress", due_date=NOW + timedelta(days=1))
    risks = detect_risks([due_soon, stalled, overdue, blocked], _cfg())
    assert [r.ticket.key for r in risks] == ["A-1", "A-2", "A-3", "A-4"]


def test_build_jql_contains_project_and_thresholds():
    jql = build_jql("ABC", stalled_days=4, due_soon_days=3)
    assert 'project = "ABC"' in jql
    assert "updated <= -4d" in jql
    assert "duedate <= 3d" in jql
    assert "ORDER BY" in jql


def test_build_jql_appends_extra():
    jql = build_jql("ABC", 3, 2, extra_jql='fixVersion = "v1"')
    assert 'fixVersion = "v1"' in jql
