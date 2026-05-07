"""Classify Jira tickets into risk categories."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .config import RiskConfig
from .models import JiraTicket, RiskCategory, RiskTicket, SEVERITY


def build_jql(
    project_key: str,
    stalled_days: int,
    due_soon_days: int,
    extra_jql: str = "",
) -> str:
    """JQL covering all four risk categories.

    statusCategory != Done excludes completed work. We still re-classify in
    Python so the category attribution and severity ranking are explicit.
    """
    clauses = [
        # Blocked
        'status = "Blocked"',
        'labels = "blocker"',
        # Stalled (in-progress, no recent update)
        f'(statusCategory = "In Progress" AND updated <= -{stalled_days}d)',
        # Overdue
        '(duedate < now() AND statusCategory != Done)',
        # Due soon
        f'(duedate >= now() AND duedate <= {due_soon_days}d AND statusCategory != Done)',
    ]
    base = (
        f'project = "{project_key}" AND statusCategory != Done '
        f'AND ({" OR ".join(clauses)})'
    )
    if extra_jql:
        base = f"({base}) AND ({extra_jql})"
    return base + " ORDER BY priority DESC, updated ASC"


def detect_risks(tickets: list[JiraTicket], cfg: RiskConfig) -> list[RiskTicket]:
    now = datetime.now(timezone.utc)
    out: list[RiskTicket] = []
    for t in tickets:
        cat, detail = _classify(t, cfg, now)
        if cat is None:
            continue
        out.append(RiskTicket(ticket=t, category=cat, detail=detail))
    out.sort(key=lambda r: (-SEVERITY[r.category], _aware_or_min(r.ticket.updated)))
    return out


def _classify(
    t: JiraTicket, cfg: RiskConfig, now: datetime
) -> tuple[Optional[RiskCategory], str]:
    status_lower = (t.status or "").lower()
    labels_lower = [l.lower() for l in (t.labels or [])]

    # 1. Blocked (highest severity)
    if "block" in status_lower or "blocker" in labels_lower:
        return RiskCategory.BLOCKED, f"status: {t.status or 'blocker label'}"

    # 2. Overdue
    if t.due_date:
        due = _aware(t.due_date)
        if due < now:
            days_over = (now - due).days
            return RiskCategory.OVERDUE, f"due {days_over}d ago"

    # 3. Stalled (in-progress, no update)
    if "in progress" in status_lower and t.updated:
        days_since = (now - _aware(t.updated)).days
        if days_since >= cfg.stalled_days:
            return RiskCategory.STALLED, f"no update in {days_since}d"

    # 4. Due soon
    if t.due_date:
        days_until = (_aware(t.due_date) - now).days
        if 0 <= days_until <= cfg.due_soon_days:
            return RiskCategory.DUE_SOON, (
                "due today" if days_until == 0 else f"due in {days_until}d"
            )

    return None, ""


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _aware_or_min(dt: Optional[datetime]) -> datetime:
    return _aware(dt) if dt else datetime.min.replace(tzinfo=timezone.utc)
