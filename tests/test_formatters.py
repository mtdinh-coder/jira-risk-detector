"""Tests for Slack Block Kit formatters."""
from datetime import datetime, timezone

from src.formatters import team_channel_blocks, tpm_dm_blocks
from src.models import JiraTicket, RiskCategory, RiskTicket


def _risk(key="ABC-1", category=RiskCategory.BLOCKED, **kw):
    t = JiraTicket(
        key=key,
        url=f"https://x/browse/{key}",
        summary=kw.get("summary", "example summary"),
        status=kw.get("status", "Blocked"),
        priority=kw.get("priority", "High"),
        labels=kw.get("labels", []),
        assignee_name=kw.get("assignee_name", "Alice"),
        assignee_email=kw.get("assignee_email", "alice@x.com"),
        qa_name=kw.get("qa_name"),
        qa_email=kw.get("qa_email"),
        due_date=kw.get("due_date"),
        updated=kw.get("updated", datetime.now(timezone.utc)),
    )
    return RiskTicket(ticket=t, category=category, detail="status: Blocked", ai_summary="Waiting on infra team.")


def test_tpm_dm_no_risks_renders_clean_message():
    text, blocks = tpm_dm_blocks([], "ABC")
    assert "no at-risk" in text.lower()
    assert any("white_check_mark" in str(b) for b in blocks)


def test_tpm_dm_with_risks_includes_link_and_owner():
    blocks_str = str(tpm_dm_blocks([_risk()], "ABC")[1])
    assert "ABC-1" in blocks_str
    assert "Alice" in blocks_str
    assert "Waiting on infra team" in blocks_str


def test_team_channel_mentions_assignee_when_lookup_succeeds():
    def lookup(email):
        return "U999" if email == "alice@x.com" else None

    _, blocks = team_channel_blocks([_risk()], lookup, "ABC")
    assert "<@U999>" in str(blocks)


def test_team_channel_falls_back_to_name_when_lookup_fails():
    def lookup(_email):
        return None

    _, blocks = team_channel_blocks([_risk()], lookup, "ABC")
    body = str(blocks)
    assert "Alice" in body
    assert "<@" not in body


def test_team_channel_dedups_when_assignee_and_qa_same_user():
    def lookup(_email):
        return "U_SAME"

    r = _risk(qa_name="Alice", qa_email="alice@x.com")
    _, blocks = team_channel_blocks([r], lookup, "ABC")
    assert str(blocks).count("<@U_SAME>") == 1


def test_team_channel_no_risks_says_all_clear():
    text, _ = team_channel_blocks([], lambda _e: None, "ABC")
    assert "all clear" in text.lower() or "no at-risk" in text.lower()
