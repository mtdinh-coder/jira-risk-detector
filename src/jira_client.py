"""Read-only Jira REST API v3 client."""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any, Optional

import requests

from .config import JiraConfig
from .models import Comment, JiraTicket

log = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, config: JiraConfig):
        self.config = config
        token = base64.b64encode(f"{config.email}:{config.api_token}".encode()).decode()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def search(self, jql: str, fields: list[str], max_total: int = 200) -> list[dict]:
        url = f"{self.config.base_url}/rest/api/3/search"
        all_issues: list[dict] = []
        start_at = 0
        page_size = 100
        while True:
            r = self.session.get(
                url,
                params={
                    "jql": jql,
                    "fields": ",".join(fields),
                    "startAt": start_at,
                    "maxResults": page_size,
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)
            total = data.get("total", 0)
            start_at += len(issues)
            if start_at >= total or not issues or len(all_issues) >= max_total:
                break
        return all_issues[:max_total]

    def get_comments(self, issue_key: str, max_comments: int = 8) -> list[Comment]:
        url = f"{self.config.base_url}/rest/api/3/issue/{issue_key}/comment"
        r = self.session.get(
            url,
            params={"orderBy": "-created", "maxResults": max_comments},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return [_parse_comment(c) for c in data.get("comments", [])]

    def fetch_candidates(self, jql: str) -> list[JiraTicket]:
        fields = [
            "summary",
            "status",
            "priority",
            "labels",
            "assignee",
            "duedate",
            "updated",
        ]
        if self.config.qa_field:
            fields.append(self.config.qa_field)
        raw = self.search(jql, fields)
        return [self._to_ticket(i) for i in raw]

    def _to_ticket(self, raw: dict) -> JiraTicket:
        f = raw["fields"]
        assignee = f.get("assignee") or {}
        qa_raw = f.get(self.config.qa_field) if self.config.qa_field else None
        qa = qa_raw if isinstance(qa_raw, dict) else {}
        return JiraTicket(
            key=raw["key"],
            url=f"{self.config.base_url}/browse/{raw['key']}",
            summary=f.get("summary", "") or "",
            status=(f.get("status") or {}).get("name", ""),
            priority=(f.get("priority") or {}).get("name") if f.get("priority") else None,
            labels=f.get("labels", []) or [],
            assignee_name=assignee.get("displayName"),
            assignee_email=assignee.get("emailAddress"),
            qa_name=qa.get("displayName"),
            qa_email=qa.get("emailAddress"),
            due_date=_parse_date(f.get("duedate")),
            updated=_parse_iso(f.get("updated")),
        )


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # Atlassian: "2026-05-07T10:30:00.000+0000" — fromisoformat needs +00:00
    try:
        if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _adf_to_text(node: Any) -> str:
    """Recursively flatten Atlassian Document Format JSON to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_adf_to_text(n) for n in node).strip()
    if isinstance(node, dict):
        ntype = node.get("type")
        if ntype == "text":
            return node.get("text", "")
        if ntype == "mention":
            return (node.get("attrs") or {}).get("text", "")
        if ntype == "emoji":
            return (node.get("attrs") or {}).get("shortName", "")
        if ntype in {"hardBreak", "rule"}:
            return "\n"
        if "content" in node:
            inner = _adf_to_text(node["content"])
            # paragraph / heading / listItem -> separate with newlines
            if ntype in {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}:
                return inner + "\n"
            return inner
    return ""


def _parse_comment(raw: dict) -> Comment:
    author = (raw.get("author") or {}).get("displayName", "Unknown")
    created = _parse_iso(raw.get("created")) or datetime.now()
    body = _adf_to_text(raw.get("body", ""))
    return Comment(author=author, created=created, body=body.strip())
