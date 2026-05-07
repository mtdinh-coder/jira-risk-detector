import logging
from datetime import date
from typing import Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, config):
        self.client = WebClient(token=config.slack_bot_token)
        self.team_channel_id = config.slack_team_channel_id
        self.tpm_email = config.slack_tpm_email
        self.dry_run = config.dry_run
        self.jira_base_url = config.jira_base_url
        self._email_to_uid: dict = {}

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    def send_all_clear(self) -> None:
        today = date.today().strftime("%B %d, %Y")
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":white_check_mark: *Jira Risk Detector — {today}*\n\n"
                        "No stalled, blocked, or overdue tickets found in the current sprint. All clear!"
                    ),
                },
            }
        ]
        self._dm_tpm(blocks, fallback="Jira Risk Detector: All clear today.")

    def send_tpm_summary(self, analyzed_tickets: list, all_tickets: list = None) -> None:
        """Send a concise DM to TPM: summary + workload chart per assignee."""
        from collections import defaultdict
        today = date.today().strftime("%B %d, %Y")

        # --- Workload chart from all_tickets ---
        chart_text = ""
        if all_tickets:
            # assignee → status → count
            workload: dict = defaultdict(lambda: defaultdict(int))
            emails: dict = {}
            for t in all_tickets:
                name = t.assignee_name or "Unassigned"
                workload[name][t.status] += 1
                if t.assignee_email:
                    emails[name] = t.assignee_email

            STATUS_ORDER = ["In Progress", "In Review", "Blocked"]
            STATUS_ICON = {"In Progress": "🟡", "In Review": "🔵", "Blocked": "🔴"}

            chart_lines = [":bar_chart: *Workload by Assignee*\n"]
            for name, counts in sorted(workload.items(), key=lambda x: -sum(x[1].values())):
                total = sum(counts.values())
                mention = self._resolve_mention(emails.get(name), name)
                chart_lines.append(f"*{mention}* — {total} ticket{'s' if total != 1 else ''}")
                for status in STATUS_ORDER:
                    n = counts.get(status, 0)
                    if n == 0:
                        continue
                    icon = STATUS_ICON.get(status, "⚪")
                    chart_lines.append(f"  {icon} {status}: *{n}*")
                chart_lines.append("")
            chart_text = "\n".join(chart_lines)

        # --- At-risk summary grouped by project → assignee ---
        by_project: dict = defaultdict(lambda: defaultdict(list))
        for ticket, analysis in analyzed_tickets:
            project = ticket.key.split("-")[0]
            assignee = ticket.assignee_name or "Unassigned"
            by_project[project][assignee].append((ticket, analysis))

        summary_lines = [f":rotating_light: *At-Risk Summary — {today}*\n"]
        for project, assignees in sorted(by_project.items()):
            summary_lines.append(f"*{project}*")
            for assignee, items in sorted(assignees.items()):
                mention = self._resolve_mention(items[0][0].assignee_email, assignee)
                ticket_keys = ", ".join(f"<{self.jira_base_url}/browse/{t.key}|{t.key}>" for t, _ in items)
                blocked = sum(1 for t, _ in items if t.is_blocked_flag)
                overdue = sum(1 for t, _ in items if t.is_overdue)
                stale_days = max(t.days_since_update for t, _ in items)
                if blocked:
                    note = f"{blocked} blocked"
                elif overdue:
                    note = f"{overdue} overdue"
                else:
                    note = f"WIP {stale_days}d no update"
                summary_lines.append(f"  • {mention} — {len(items)} ticket(s), {note}: {ticket_keys}")
            summary_lines.append("")

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)}},
        ]
        if chart_text:
            blocks.append({"type": "divider"})
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chart_text}})

        self._dm_tpm(blocks, fallback="Daily Jira Summary")

    def send_tpm_report(self, analyzed_tickets: list) -> None:
        """Post the detailed per-ticket report to the team channel."""
        today = date.today().strftime("%B %d, %Y")
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 Jira Risk Report — {today}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{len(analyzed_tickets)} ticket(s)* flagged as stalled, blocked, or at risk.",
                },
            },
            {"type": "divider"},
        ]
        for ticket, analysis in analyzed_tickets:
            blocks.extend(self._ticket_blocks(ticket, analysis))
            blocks.append({"type": "divider"})

        if self.dry_run:
            import json
            logger.info("[DRY RUN] Channel report blocks:\n%s", json.dumps(blocks, indent=2))
            return
        try:
            self.client.chat_postMessage(
                channel=self.team_channel_id,
                blocks=blocks,
                text="Jira Risk Report",
            )
        except SlackApiError as e:
            logger.error("Failed to post channel report: %s", e.response["error"])

    def send_nudge_reminders(self, nudge_tickets: list) -> None:
        """Post a gentle reminder in the team channel for tickets with no recent update."""
        if not nudge_tickets:
            return
        today = date.today().strftime("%B %d, %Y")
        lines = [f":bell: *Ticket Update Reminder — {today}*\n"]
        for ticket in nudge_tickets:
            mention = self._resolve_mention(ticket.assignee_email, ticket.assignee_name)
            url = f"{self.jira_base_url}/browse/{ticket.key}"
            lines.append(
                f":pencil2: {mention} — <{url}|{ticket.key}> *{ticket.summary}*\n"
                f"   › No update for *{ticket.days_since_update} day(s)* — please add a comment or move the ticket forward."
            )
        text = "\n\n".join(lines)
        if self.dry_run:
            logger.info("[DRY RUN] Nudge message:\n%s", text)
            return
        try:
            self.client.chat_postMessage(
                channel=self.team_channel_id,
                text=text,
                mrkdwn=True,
            )
        except SlackApiError as e:
            logger.error("Failed to post nudge message: %s", e.response["error"])

    def send_channel_mentions(self, analyzed_tickets: list) -> None:
        today = date.today().strftime("%B %d, %Y")
        lines = [f":rotating_light: *Jira Risk Summary — {today}*\n"]

        for ticket, analysis in analyzed_tickets:
            mention = self._resolve_mention(ticket.assignee_email, ticket.assignee_name)
            icon = "🔴" if ticket.is_blocked_flag or ticket.is_overdue else "🟡"
            url = f"{self.jira_base_url}/browse/{ticket.key}"
            lines.append(
                f"{icon} *<{url}|{ticket.key}>* — {ticket.summary}\n"
                f"   › Assigned: {mention}  |  Status: *{ticket.status}*  |  {ticket.days_since_update}d stale\n"
                f"   › {analysis.risk_reason}"
            )

        text = "\n\n".join(lines)
        if self.dry_run:
            logger.info("[DRY RUN] Channel message:\n%s", text)
            return
        try:
            self.client.chat_postMessage(
                channel=self.team_channel_id,
                text=text,
                mrkdwn=True,
            )
        except SlackApiError as e:
            logger.error("Failed to post channel message: %s", e.response["error"])

    # ------------------------------------------------------------------ #
    #  Block builders                                                      #
    # ------------------------------------------------------------------ #

    def _ticket_blocks(self, ticket, analysis) -> list:
        icon = "🔴" if ticket.is_blocked_flag or ticket.is_overdue else "🟡"
        mention = self._resolve_mention(ticket.assignee_email, ticket.assignee_name)
        url = f"{self.jira_base_url}/browse/{ticket.key}"

        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{icon} *<{url}|{ticket.key}>* — {ticket.summary}\n"
                        f"*Assignee:* {mention}   *Status:* {ticket.status}\n"
                        f":arrow_right: {analysis.recommended_action}"
                    ),
                },
            },
        ]

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _dm_tpm(self, blocks: list, fallback: str = "") -> None:
        if self.dry_run:
            import json
            logger.info("[DRY RUN] TPM DM blocks:\n%s", json.dumps(blocks, indent=2))
            return
        uid = self._lookup_slack_uid(self.tpm_email)
        if not uid:
            logger.error("Cannot resolve TPM Slack UID for email: %s", self.tpm_email)
            return
        try:
            conv = self.client.conversations_open(users=uid)
            channel = conv["channel"]["id"]
            self.client.chat_postMessage(channel=channel, blocks=blocks, text=fallback)
        except SlackApiError as e:
            logger.error("Failed to DM TPM (%s): %s", self.tpm_email, e.response["error"])

    def _resolve_mention(self, email: Optional[str], display_name: Optional[str]) -> str:
        if email:
            uid = self._lookup_slack_uid(email)
            if uid:
                return f"<@{uid}>"
        return display_name or "Unassigned"

    def _lookup_slack_uid(self, email: str) -> Optional[str]:
        if email in self._email_to_uid:
            return self._email_to_uid[email]
        try:
            result = self.client.users_lookupByEmail(email=email)
            uid = result["user"]["id"]
        except SlackApiError as e:
            if e.response["error"] not in ("users_not_found", "user_not_found"):
                logger.warning("Slack UID lookup failed for %s: %s", email, e.response["error"])
            uid = None
        self._email_to_uid[email] = uid
        return uid
