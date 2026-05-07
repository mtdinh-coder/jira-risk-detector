"""Domain models for the risk detector."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RiskCategory(str, Enum):
    BLOCKED = "Blocked"
    OVERDUE = "Overdue"
    STALLED = "Stalled"
    DUE_SOON = "Due Soon"


SEVERITY = {
    RiskCategory.BLOCKED: 4,
    RiskCategory.OVERDUE: 3,
    RiskCategory.STALLED: 2,
    RiskCategory.DUE_SOON: 1,
}


@dataclass
class Comment:
    author: str
    created: datetime
    body: str


@dataclass
class JiraTicket:
    key: str
    url: str
    summary: str
    status: str
    priority: Optional[str]
    labels: list[str]
    assignee_name: Optional[str]
    assignee_email: Optional[str]
    qa_name: Optional[str]
    qa_email: Optional[str]
    due_date: Optional[datetime]
    updated: Optional[datetime]
    comments: list[Comment] = field(default_factory=list)


@dataclass
class RiskTicket:
    ticket: JiraTicket
    category: RiskCategory
    detail: str
    ai_summary: str = ""
