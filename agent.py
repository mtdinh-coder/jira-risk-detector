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

        if not at_risk_tickets:
            logger.info("No at-risk tickets. Sending all-clear.")
            self.notifier.send_all_clear()
            return

        logger.info("%d at-risk ticket(s) found. Analyzing...", len(at_risk_tickets))

        analyzed = []
        for ticket in at_risk_tickets:
            try:
                analysis = self.analyzer.analyze_ticket(ticket)
                analyzed.append((ticket, analysis))
                logger.info("%s: %s", ticket.key, analysis.risk_reason)
            except Exception:
                logger.exception("Failed to analyze %s", ticket.key)

        if not analyzed:
            logger.error("All analyses failed. Aborting notifications.")
            return

        try:
            all_tickets = self.jira.get_all_active_tickets()
            self.notifier.send_tpm_summary(analyzed, all_tickets=all_tickets)
        except Exception:
            logger.exception("Failed to send TPM summary")

        try:
            self.notifier.send_tpm_report(analyzed)  # detail → channel
        except Exception:
            logger.exception("Failed to send channel report")
