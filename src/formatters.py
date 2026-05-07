"""Slack Block Kit formatters for the TPM DM and team channel post."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from .models import RiskCategory, RiskTicket

EMOJI: dict[RiskCategory, str] = {
    RiskCategory.BLOCKED: ":no_entry:",
    RiskCategory.OVERDUE: ":red_circle:",
    RiskCategory.STALLED: ":large_yellow_circle:",
    RiskCategory.DUE_SOON: ":large_orange_circle:",
}


def tpm_dm_blocks(risks: list[RiskTicket], project_key: str) -> tuple[str, list[dict]]:
    today = datetime.now().strftime("%Y-%m-%d")

    if not risks:
        text = f"Daily Jira risk check — {project_key} — {today}: no at-risk tickets."
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Daily Jira risk check — `{project_key}` — {today}*\n"
                        ":white_check_mark: No at-risk tickets today."
                    ),
                },
            }
        ]
        return text, blocks

    counts: dict[RiskCategory, int] = {}
    for r in risks:
        counts[r.category] = counts.get(r.category, 0) + 1
    summary_parts = [f"{EMOJI[c]} *{c.value}*: {n}" for c, n in counts.items()]
    header = (
        f"*Daily Jira risk check — `{project_key}` — {today}*\n"
        f"Found *{len(risks)}* at-risk ticket(s):  " + "  ·  ".join(summary_parts)
    )

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "divider"},
    ]

    for r in risks:
        t = r.ticket
        title = _truncate(t.summary, 140)
        owner = t.assignee_name or "_unassigned_"
        prio = f"  ·  *Priority:* {t.priority}" if t.priority else ""
        line1 = (
            f"{EMOJI[r.category]} *<{t.url}|{t.key}>*  ·  "
            f"*{r.category.value}*  ·  _{r.detail}_"
        )
        line2 = f"*Title:* {title}\n*Owner:* {owner}{prio}"
        line3 = f"*Why:* {r.ai_summary or '_no AI summary_'}"
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{line1}\n{line2}\n{line3}"},
            }
        )
        blocks.append({"type": "divider"})

    plain = (
        f"Daily Jira risk check — {project_key} — {len(risks)} ticket(s) need attention"
    )
    return plain, blocks


def team_channel_blocks(
    risks: list[RiskTicket],
    mention_for_email: Callable[[Optional[str]], Optional[str]],
    project_key: str,
) -> tuple[str, list[dict]]:
    today = datetime.now().strftime("%Y-%m-%d")

    if not risks:
        text = f"Daily Jira check — {project_key} — {today}: all clear."
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":white_check_mark: *Daily Jira check — `{project_key}` — {today}* "
                        "— no at-risk tickets."
                    ),
                },
            }
        ]
        return text, blocks

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":mag: *Daily Jira check — `{project_key}` — {today}* — "
                    f"*{len(risks)}* ticket(s) need attention. Owners please update:"
                ),
            },
        },
        {"type": "divider"},
    ]

    for r in risks:
        t = r.ticket
        mention_pieces: list[str] = []
        seen_uids: set[str] = set()
        for email, fallback_name in (
            (t.assignee_email, t.assignee_name),
            (t.qa_email, t.qa_name),
        ):
            if not email:
                continue
            uid = mention_for_email(email)
            if uid and uid not in seen_uids:
                mention_pieces.append(f"<@{uid}>")
                seen_uids.add(uid)
            elif not uid and fallback_name:
                mention_pieces.append(fallback_name)
        owner_str = " ".join(mention_pieces) if mention_pieces else "_no owner set_"

        text = (
            f"{EMOJI[r.category]} *<{t.url}|{t.key}>* — "
            f"{_truncate(t.summary, 100)}  ·  _{r.detail}_  →  {owner_str}"
        )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    plain = f"Daily Jira check — {project_key} — {len(risks)} ticket(s)"
    return plain, blocks


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
