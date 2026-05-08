import logging
from config import Config
from jira_client import JiraClient
from risk_analyzer import RiskAnalyzer
from slack_notifier import SlackNotifier

logger = logging.getLogger(__name__)


class JiraRiskDetectorAgent:
    def __init__(self, config: Config):
        self.config = config
        self.jira = JiraClient(config)
        self.analyzer = RiskAnalyzer(config)
        self.notifier = SlackNotifier(config)

    def run(self) -> None:
        logger.info("Scanning project: %s", self.config.jira_project_key)

        # Gentle nudge for tickets idle >= nudge_days (but not yet stalled)
        try:
            nudge_tickets = self.jira.get_nudge_tickets()
            if nudge_tickets:
                logger.info("%d ticket(s) need a nudge.", len(nudge_tickets))
                self.notifier.send_nudge_reminders(nudge_tickets)
        except Exception:
            logger.exception("Failed to process nudge tickets")

        try:
            at_risk_tickets = self.jira.get_at_risk_tickets()
        except Exception:
            logger.exception("Failed to fetch Jira tickets")
            return

        try:
            subtasks = self.jira.get_at_risk_subtasks()
            logger.info("%d at-risk subtask(s) found.", len(subtasks))
        except Exception:
            logger.exception("Failed to fetch subtasks")
            subtasks = []

        if not at_risk_tickets and not subtasks:
            logger.info("No at-risk tickets. Sending all-clear.")
            self.notifier.send_all_clear()
            return

        all_at_risk = at_risk_tickets + subtasks
        logger.info("%d ticket(s) + %d subtask(s) found. Analyzing...", len(at_risk_tickets), len(subtasks))

        analyzed = []
        for ticket in all_at_risk:
            try:
                analysis = self.analyzer.analyze_ticket(ticket)
                analyzed.append((ticket, analysis))
                logger.info("%s: %s", ticket.key, analysis.risk_reason)
            except Exception:
                logger.exception("Failed to analyze %s", ticket.key)

        if not analyzed:
            logger.error("All analyses failed. Aborting notifications.")
            return

        analyzed_main = [(t, a) for t, a in analyzed if not t.key.startswith("subtask")]
        # Split by whether summary starts with [PARENT-KEY] pattern
        import re
        analyzed_tickets_only = [(t, a) for t, a in analyzed if not re.match(r'^\[.+-\d+\]', t.summary)]
        analyzed_subtasks_only = [(t, a) for t, a in analyzed if re.match(r'^\[.+-\d+\]', t.summary)]

        try:
            all_tickets = self.jira.get_all_active_tickets()
            self.notifier.send_tpm_summary(analyzed_tickets_only, all_tickets=all_tickets, subtasks=analyzed_subtasks_only)
        except Exception:
            logger.exception("Failed to send TPM summary")

        try:
            self.notifier.send_tpm_report(analyzed_tickets_only, subtasks=analyzed_subtasks_only)
        except Exception:
            logger.exception("Failed to send channel report")
