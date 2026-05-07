from dataclasses import dataclass, field
import os


@dataclass
class Config:
    # Jira
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str
    jira_extra_jql: str
    jira_exclude_assignees: list  # list of display names to skip

    # Risk thresholds
    stalled_days: int
    nudge_days: int
    due_soon_days: int
    comments_for_summary: int

    # Anthropic
    anthropic_api_key: str
    anthropic_model: str

    # Slack
    slack_bot_token: str
    slack_team_channel_id: str
    slack_tpm_email: str

    # Behavior
    dry_run: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        tpm_email = os.environ.get("SLACK_TPM_EMAIL") or os.environ["JIRA_EMAIL"]
        return cls(
            jira_base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
            jira_email=os.environ["JIRA_EMAIL"],
            jira_api_token=os.environ["JIRA_API_TOKEN"],
            jira_project_key=os.environ["JIRA_PROJECT_KEY"],
            jira_extra_jql=os.environ.get("JIRA_EXTRA_JQL", ""),
            jira_exclude_assignees=[
                n.strip() for n in os.environ.get("JIRA_EXCLUDE_ASSIGNEES", "").split(",") if n.strip()
            ],
            stalled_days=int(os.environ.get("STALLED_DAYS", "3")),
            nudge_days=int(os.environ.get("NUDGE_DAYS", "1")),
            due_soon_days=int(os.environ.get("DUE_SOON_DAYS", "2")),
            comments_for_summary=int(os.environ.get("COMMENTS_FOR_SUMMARY", "8")),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7"),
            slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
            slack_team_channel_id=os.environ["SLACK_TEAM_CHANNEL_ID"],
            slack_tpm_email=tpm_email,
            dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )
