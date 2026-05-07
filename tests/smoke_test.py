"""Standalone smoke test runnable without pytest. Mirrors test_*.py assertions."""
from datetime import datetime, timedelta, timezone
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import RiskConfig
from src.models import JiraTicket, RiskCategory, RiskTicket
from src.risk_detector import build_jql, detect_risks
from src.formatters import tpm_dm_blocks, team_channel_blocks

NOW = datetime.now(timezone.utc)


def mk(**kw):
    base = dict(
        key="ABC-1", url="https://x/browse/ABC-1", summary="example",
        status="In Progress", priority="High", labels=[],
        assignee_name="Alice", assignee_email="alice@x.com",
        qa_name=None, qa_email=None, due_date=None, updated=NOW,
    )
    base.update(kw)
    return JiraTicket(**base)


cfg = RiskConfig(stalled_days=3, due_soon_days=2, comments_for_summary=8)
checks = []

def chk(name, condition):
    if not condition:
        print(f"FAIL: {name}")
        sys.exit(1)
    checks.append(name)

# risk_detector
chk("blocked status",
    detect_risks([mk(status="Blocked", updated=NOW - timedelta(days=10))], cfg)[0].category == RiskCategory.BLOCKED)
chk("blocker label",
    detect_risks([mk(status="In Progress", labels=["blocker"])], cfg)[0].category == RiskCategory.BLOCKED)
chk("overdue",
    detect_risks([mk(due_date=NOW - timedelta(days=4))], cfg)[0].category == RiskCategory.OVERDUE)
chk("stalled",
    detect_risks([mk(updated=NOW - timedelta(days=5))], cfg)[0].category == RiskCategory.STALLED)
chk("due soon",
    detect_risks([mk(due_date=NOW + timedelta(days=1))], cfg)[0].category == RiskCategory.DUE_SOON)
chk("recent in-progress not flagged",
    detect_risks([mk(updated=NOW - timedelta(hours=2))], cfg) == [])
chk("done not flagged",
    detect_risks([mk(status="Done", updated=NOW - timedelta(days=30))], cfg) == [])

b = mk(key="A-1", status="Blocked")
o = mk(key="A-2", due_date=NOW - timedelta(days=1))
s = mk(key="A-3", updated=NOW - timedelta(days=5))
ds = mk(key="A-4", due_date=NOW + timedelta(days=1))
order = [r.ticket.key for r in detect_risks([ds, s, o, b], cfg)]
chk("severity order", order == ["A-1", "A-2", "A-3", "A-4"])

jql = build_jql("ABC", 4, 3)
chk("jql project",  'project = "ABC"' in jql)
chk("jql stalled days", "updated <= -4d" in jql)
chk("jql due soon", "duedate <= 3d" in jql)
chk("jql extra", 'fixVersion = "v1"' in build_jql("ABC", 3, 2, 'fixVersion = "v1"'))

# formatters
text, blocks = tpm_dm_blocks([], "ABC")
chk("dm no risks text", "no at-risk" in text.lower())

risk = RiskTicket(ticket=mk(status="Blocked"), category=RiskCategory.BLOCKED,
                  detail="status: Blocked", ai_summary="Waiting on infra.")
text, blocks = tpm_dm_blocks([risk], "ABC")
chk("dm body content", "ABC-1" in str(blocks) and "Alice" in str(blocks) and "Waiting on infra" in str(blocks))

_, blocks = team_channel_blocks([risk], lambda e: "U999" if e == "alice@x.com" else None, "ABC")
chk("team mention", "<@U999>" in str(blocks))

_, blocks = team_channel_blocks([risk], lambda _e: None, "ABC")
chk("team fallback name", "Alice" in str(blocks) and "<@" not in str(blocks))

risk2 = RiskTicket(
    ticket=mk(status="Blocked", qa_name="Alice", qa_email="alice@x.com"),
    category=RiskCategory.BLOCKED, detail="x",
)
_, blocks = team_channel_blocks([risk2], lambda _e: "U_SAME", "ABC")
chk("dedup same user", str(blocks).count("<@U_SAME>") == 1)

print(f"ALL {len(checks)} CHECKS PASSED")
for c in checks:
    print(f"  - {c}")
