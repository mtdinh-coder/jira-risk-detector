"""Load configuration from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

# Load .env from project root (parent of src/) so it works regardless of cwd.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _required(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key} (check {_ENV_PATH})")
    return val


class JiraConfig(BaseModel):
    base_url: str
    email: str
    api_token: str
    project_key: str
    extra_jql: str = ""
    qa_field: str = ""


class AnthropicConfig(BaseModel):
    api_key: str
    model: str = "claude-haiku-4-5-20251001"


class SlackConfig(BaseModel):
    bot_token: str
    team_channel_id: str
    tpm_email: str


class RiskConfig(BaseModel):
    stalled_days: int = 3
    due_soon_days: int = 2
    comments_for_summary: int = 8


class AppConfig(BaseModel):
    jira: JiraConfig
    anthropic: AnthropicConfig
    slack: SlackConfig
    risk: RiskConfig
    dry_run: bool = False
    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            jira=JiraConfig(
                base_url=_required("JIRA_BASE_URL").rstrip("/"),
                email=_required("JIRA_EMAIL"),
                api_token=_required("JIRA_API_TOKEN"),
                project_key=_required("JIRA_PROJECT_KEY"),
                extra_jql=os.getenv("JIRA_EXTRA_JQL", "").strip(),
                qa_field=os.getenv("JIRA_QA_FIELD", "").strip(),
            ),
            anthropic=AnthropicConfig(
                api_key=_required("ANTHROPIC_API_KEY"),
                model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            ),
            slack=SlackConfig(
                bot_token=_required("SLACK_BOT_TOKEN"),
                team_channel_id=_required("SLACK_TEAM_CHANNEL_ID"),
                tpm_email=os.getenv("SLACK_TPM_EMAIL", "").strip() or _required("JIRA_EMAIL"),
            ),
            risk=RiskConfig(
                stalled_days=int(os.getenv("STALLED_DAYS", "3")),
                due_soon_days=int(os.getenv("DUE_SOON_DAYS", "2")),
                comments_for_summary=int(os.getenv("COMMENTS_FOR_SUMMARY", "8")),
            ),
            dry_run=os.getenv("DRY_RUN", "false").strip().lower() in {"1", "true", "yes"},
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )
