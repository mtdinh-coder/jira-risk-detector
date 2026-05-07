"""Entry point — fetch, classify, summarize, notify."""
from __future__ import annotations

import json
import logging
import sys

from .ai_summarizer import Summarizer
from .config import AppConfig
from .formatters import team_channel_blocks, tpm_dm_blocks
from .jira_client import JiraClient
from .risk_detector import build_jql, detect_risks
from .slack_notifier import SlackNotifier


def main() -> int:
    try:
        cfg = AppConfig.load()
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: config load failed: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    log = logging.getLogger("agent")
    log.info(
        "Starting Jira Risk Detector — project=%s dry_run=%s",
        cfg.jira.project_key,
        cfg.dry_run,
    )

    jira = JiraClient(cfg.jira)
    jql = build_jql(
        cfg.jira.project_key,
        cfg.risk.stalled_days,
        cfg.risk.due_soon_days,
        cfg.jira.extra_jql,
    )
    log.info("JQL: %s", jql)

    candidates = jira.fetch_candidates(jql)
    log.info("Fetched %d candidate ticket(s)", len(candidates))

    risks = detect_risks(candidates, cfg.risk)
    log.info("Classified %d at-risk ticket(s)", len(risks))

    if risks:
        for r in risks:
            r.ticket.comments = jira.get_comments(
                r.ticket.key, cfg.risk.comments_for_summary
            )
        summarizer = Summarizer(cfg.anthropic)
        for r in risks:
            r.ai_summary = summarizer.summarize(r)
            log.info("[%s] %s — %s", r.ticket.key, r.category.value, r.ai_summary[:120])

    slack = SlackNotifier(cfg.slack.bot_token)

    tpm_text, tpm_blocks = tpm_dm_blocks(risks, cfg.jira.project_key)
    team_text, team_blocks = team_channel_blocks(
        risks, slack.user_id_by_email, cfg.jira.project_key
    )

    if cfg.dry_run:
        log.info("DRY RUN — would DM TPM (%s):", cfg.slack.tpm_email)
        print(tpm_text)
        print(json.dumps(tpm_blocks, indent=2, ensure_ascii=False))
        log.info("DRY RUN — would post to channel %s:", cfg.slack.team_channel_id)
        print(team_text)
        print(json.dumps(team_blocks, indent=2, ensure_ascii=False))
        return 0

    tpm_uid = slack.user_id_by_email(cfg.slack.tpm_email)
    if not tpm_uid:
        log.error(
            "Could not resolve Slack user for TPM email %s — skipping DM",
            cfg.slack.tpm_email,
        )
    else:
        dm_channel = slack.open_dm(tpm_uid)
        if dm_channel and slack.post(dm_channel, tpm_text, tpm_blocks):
            log.info("Sent DM to TPM (%s)", cfg.slack.tpm_email)

    # Public channel: only post on days with risks to avoid noise.
    if risks:
        if slack.post(cfg.slack.team_channel_id, team_text, team_blocks):
            log.info("Posted to team channel %s", cfg.slack.team_channel_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
