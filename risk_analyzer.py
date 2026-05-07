from dataclasses import dataclass
from typing import Optional


@dataclass
class TicketAnalysis:
    risk_reason: str
    blocking_factor: str
    key_evidence: Optional[str]
    recommended_action: str


class RiskAnalyzer:
    def __init__(self, config):
        self.stalled_days = config.stalled_days
        self.due_soon_days = config.due_soon_days

    def analyze_ticket(self, ticket) -> TicketAnalysis:
        risk_reason = self._risk_reason(ticket)
        blocking_factor = self._blocking_factor(ticket)
        key_evidence = self._key_evidence(ticket)
        recommended_action = self._recommended_action(ticket)
        return TicketAnalysis(
            risk_reason=risk_reason,
            blocking_factor=blocking_factor,
            key_evidence=key_evidence,
            recommended_action=recommended_action,
        )

    def _risk_reason(self, ticket) -> str:
        reasons = []
        if ticket.is_blocked_flag:
            reasons.append(f"ticket is marked as Blocked")
        if ticket.is_overdue:
            days_over = abs(ticket.days_until_due)
            reasons.append(f"overdue by {days_over} day(s)")
        elif ticket.days_until_due is not None and 0 <= ticket.days_until_due <= self.due_soon_days:
            reasons.append(f"due in {ticket.days_until_due} day(s)")
        if ticket.days_since_update >= self.stalled_days:
            reasons.append(f"no update for {ticket.days_since_update} day(s)")
        return "Ticket is at risk: " + ", ".join(reasons) if reasons else "Ticket flagged for review"

    def _blocking_factor(self, ticket) -> str:
        if ticket.is_blocked_flag:
            if "blocked" in [lb.lower() for lb in ticket.labels]:
                return "Labeled as 'blocked'"
            if "impediment" in [lb.lower() for lb in ticket.labels]:
                return "Labeled as 'impediment'"
            return "Status is Blocked"
        if ticket.is_overdue:
            return f"Past due date with status still '{ticket.status}'"
        if ticket.days_since_update >= self.stalled_days:
            return f"No activity for {ticket.days_since_update} day(s) — may be forgotten or waiting"
        if ticket.days_until_due is not None and 0 <= ticket.days_until_due <= self.due_soon_days:
            return f"Due soon ({ticket.days_until_due}d) but status is still '{ticket.status}'"
        return "No comments explain the current delay"

    def _key_evidence(self, ticket) -> Optional[str]:
        if not ticket.comments:
            return None
        # Surface the most recent comment as context
        latest = ticket.comments[0]
        if latest.body.strip():
            preview = latest.body.strip()[:200]
            return f"[{latest.created}] {latest.author}: {preview}"
        return None

    def _recommended_action(self, ticket) -> str:
        if ticket.is_blocked_flag:
            assignee = ticket.assignee_name or "assignee"
            return f"Follow up with {assignee} to identify and remove the blocker"
        if ticket.is_overdue:
            assignee = ticket.assignee_name or "assignee"
            return f"Contact {assignee} immediately — ticket is past due date"
        if ticket.days_until_due is not None and 0 <= ticket.days_until_due <= self.due_soon_days:
            return f"Check with {ticket.assignee_name or 'assignee'} — due in {ticket.days_until_due}d"
        if ticket.days_since_update >= self.stalled_days:
            return f"Ask {ticket.assignee_name or 'assignee'} for a status update — {ticket.days_since_update}d without activity"
        return "Review ticket status with the team"
