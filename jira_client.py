from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import requests


@dataclass
class JiraComment:
    author: str
    body: str
    created: str  # YYYY-MM-DD


@dataclass
class JiraTicket:
    key: str
    summary: str
    status: str
    assignee_name: Optional[str]
    assignee_email: Optional[str]
    priority: str
    updated: str
    due_date: Optional[str]
    labels: list
    comments: list  # list[JiraComment]
    is_blocked_flag: bool

    @property
    def days_since_update(self) -> int:
        """Number of working days (Mon–Fri) since last update."""
        updated_dt = datetime.fromisoformat(self.updated.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        count = 0
        current = updated_dt
        while current.date() < now.date():
            current += __import__('datetime').timedelta(days=1)
            if current.weekday() < 5:  # Mon=0 ... Fri=4
                count += 1
        return count

    @property
    def days_until_due(self) -> Optional[int]:
        if not self.due_date:
            return None
        due_dt = datetime.fromisoformat(self.due_date)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        return (due_dt - datetime.now(timezone.utc)).days

    @property
    def is_overdue(self) -> bool:
        d = self.days_until_due
        return d is not None and d < 0

    @property
    def is_due_soon(self, threshold: int = 2) -> bool:
        d = self.days_until_due
        return d is not None and 0 <= d <= threshold


class JiraClient:
    def __init__(self, config):
        self.base_url = config.jira_base_url
        self.auth = None  # not used — Bearer token below
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {config.jira_api_token}",
        }
        self.config = config

    def get_all_active_tickets(self) -> list:
        """Fetch all active tickets for the workload chart (no at-risk filter)."""
        jql = (
            f'project in ({self._project_list()}) '
            f'{self._sprint_clause()}'
            f'AND status in ("To Do", "In Progress", "Blocked", "In Review") '
            f'AND assignee is not EMPTY'
        )
        if self.config.jira_extra_jql:
            jql += f" AND {self.config.jira_extra_jql}"

        data = self._get(
            "/rest/api/2/search",
            {
                "jql": jql,
                "maxResults": 200,
                "fields": "summary,status,assignee",
            },
        )
        tickets = [self._parse_issue(issue) for issue in data.get("issues", [])]
        return [t for t in tickets if not self._is_excluded(t)]

    def get_at_risk_tickets(self) -> list:
        jql = (
            f'project in ({self._project_list()}) '
            f'{self._sprint_clause()}'
            f'AND status in ("To Do", "In Progress", "Blocked", "In Review") '
            f'AND issuetype in standardIssueTypes()'
        )
        if self.config.jira_extra_jql:
            jql += f" AND {self.config.jira_extra_jql}"
        jql += " ORDER BY updated ASC"

        data = self._get(
            "/rest/api/2/search",
            {
                "jql": jql,
                "maxResults": 50,
                "fields": "summary,status,assignee,priority,updated,duedate,labels,comment",
            },
        )

        tickets = []
        for issue in data.get("issues", []):
            ticket = self._parse_issue(issue)
            if self._is_at_risk(ticket) and not self._is_excluded(ticket):
                tickets.append(ticket)
        return tickets

    def get_at_risk_subtasks(self) -> list:
        """Fetch subtasks that are at risk — scoped to at-risk parent tickets."""
        jql = (
            f'project in ({self._project_list()}) '
            f'{self._sprint_clause()}'
            f'AND issuetype in subTaskIssueTypes() '
            f'AND status in ("To Do", "In Progress", "Blocked", "In Review")'
        )
        if self.config.jira_extra_jql:
            jql += f" AND {self.config.jira_extra_jql}"
        jql += " ORDER BY updated ASC"

        data = self._get(
            "/rest/api/2/search",
            {
                "jql": jql,
                "maxResults": 100,
                "fields": "summary,status,assignee,priority,updated,duedate,labels,comment,parent",
            },
        )

        subtasks = []
        for issue in data.get("issues", []):
            ticket = self._parse_issue(issue)
            # Attach parent key to summary for context
            parent = issue["fields"].get("parent", {})
            parent_key = parent.get("key", "")
            if parent_key:
                ticket.summary = f"[{parent_key}] {ticket.summary}"
            if self._is_at_risk(ticket) and not self._is_excluded(ticket):
                subtasks.append(ticket)
        return subtasks

    def get_nudge_tickets(self) -> list:
        """Tickets that haven't been updated for >= nudge_days but < stalled_days."""
        if self.config.nudge_days <= 0:
            return []
        jql = (
            f'project in ({self._project_list()}) '
            f'{self._sprint_clause()}'
            f'AND status in ("In Progress", "In Review")'
        )
        if self.config.jira_extra_jql:
            jql += f" AND {self.config.jira_extra_jql}"
        jql += " ORDER BY updated ASC"

        data = self._get(
            "/rest/api/2/search",
            {
                "jql": jql,
                "maxResults": 100,
                "fields": "summary,status,assignee,priority,updated",
            },
        )
        nudge = []
        for issue in data.get("issues", []):
            ticket = self._parse_issue(issue)
            if (
                self.config.nudge_days <= ticket.days_since_update < self.config.stalled_days
                and not ticket.is_blocked_flag
                and not ticket.is_overdue
                and not self._is_excluded(ticket)
            ):
                nudge.append(ticket)
        return nudge

    def _is_excluded(self, ticket: "JiraTicket") -> bool:
        if not self.config.jira_exclude_assignees:
            return False
        name = (ticket.assignee_name or "").strip().lower()
        return name in [n.lower() for n in self.config.jira_exclude_assignees]

    def _is_at_risk(self, ticket: "JiraTicket") -> bool:
        if ticket.is_blocked_flag or ticket.is_overdue:
            return True
        if ticket.days_since_update >= self.config.stalled_days:
            return True
        d = ticket.days_until_due
        if d is not None and 0 <= d <= self.config.due_soon_days:
            return True
        return False

    def _parse_issue(self, issue: dict) -> JiraTicket:
        fields = issue["fields"]
        comment_data = fields.get("comment", {}).get("comments", [])
        n = self.config.comments_for_summary
        recent = comment_data[-n:]
        comments = [
            JiraComment(
                author=c.get("author", {}).get("displayName", "Unknown"),
                body=self._extract_text(c.get("body", ""))[:600],
                created=c.get("created", "")[:10],
            )
            for c in reversed(recent)
        ]

        labels = fields.get("labels", [])
        status_name = fields.get("status", {}).get("name", "")
        is_blocked = (
            status_name.lower() == "blocked"
            or "blocked" in [lb.lower() for lb in labels]
            or "impediment" in [lb.lower() for lb in labels]
        )

        assignee = fields.get("assignee") or {}
        return JiraTicket(
            key=issue["key"],
            summary=fields.get("summary", ""),
            status=status_name or "Unknown",
            assignee_name=assignee.get("displayName"),
            assignee_email=assignee.get("emailAddress"),
            priority=fields.get("priority", {}).get("name", "Medium"),
            updated=fields.get("updated", ""),
            due_date=fields.get("duedate"),
            labels=labels,
            comments=comments,
            is_blocked_flag=is_blocked,
        )

    def _extract_text(self, body) -> str:
        # Jira Server v2: body is plain text string
        # Jira Cloud v3: body is ADF JSON dict
        if isinstance(body, str):
            return body
        if isinstance(body, dict):
            return self._adf_to_text(body)
        return ""

    def _adf_to_text(self, node: dict, depth: int = 0) -> str:
        """Recursively extract plain text from Atlassian Document Format (ADF) JSON."""
        if depth > 10:
            return ""
        if node.get("type") == "text":
            return node.get("text", "")
        children = [self._adf_to_text(c, depth + 1) for c in node.get("content", [])]
        sep = "\n" if node.get("type") in ("paragraph", "bulletList", "orderedList") else " "
        return sep.join(p for p in children if p)

    def _project_list(self) -> str:
        """Return comma-separated quoted project keys for use in JQL 'project in (...)'."""
        keys = [k.strip() for k in self.config.jira_project_key.split(",") if k.strip()]
        return ", ".join(f'"{k}"' for k in keys)

    def _sprint_clause(self) -> str:
        """Return sprint JQL clause if supported, empty string otherwise."""
        if not getattr(self, '_sprint_supported', None):
            try:
                self._get("/rest/api/2/search", {
                    "jql": f'project in ({self._project_list()}) AND sprint in openSprints()',
                    "maxResults": 1,
                    "fields": "summary",
                })
                self._sprint_supported = True
            except Exception:
                self._sprint_supported = False
        return "AND sprint in openSprints() " if self._sprint_supported else ""

    def _get(self, endpoint: str, params: dict = None) -> dict:
        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
