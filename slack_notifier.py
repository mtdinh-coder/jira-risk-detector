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
        text = (
            f":white_check_mark: *Jira Risk Detector — {today}*\n\n"
            "Các tasks đã được cập nhật đầy đủ. Chúc mọi người một ngày làm việc năng suất! 🎉"
        )
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        self._dm_tpm(blocks, fallback="Jira Risk Detector: All clear today.")
        # Also post to channel
        if self.dry_run:
            import json
            logger.info("[DRY RUN] All-clear channel message:\n%s", text)
            return
        try:
            self.client.chat_postMessage(
                channel=self.team_channel_id,
                text=text,
                mrkdwn=True,
            )
        except SlackApiError as e:
            logger.error("Failed to post all-clear to channel: %s", e.response["error"])

    def send_tpm_summary(self, analyzed_tickets: list, all_tickets: list = None, subtasks: list = None) -> None:
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

            STATUS_ORDER = ["To Do", "In Progress", "In Review", "Blocked"]
            STATUS_ICON = {"To Do": "⚪", "In Progress": "🟡", "In Review": "🔵", "Blocked": "🔴"}

            # Build map: assignee → list of ticket keys that have at-risk subtasks
            import re as _re
            subtask_list = subtasks or []
            parent_has_subtask: dict = defaultdict(list)  # parent_key → [subtask_key]
            assignee_subtask_parents: dict = defaultdict(set)  # assignee_name → {parent_key}
            for t, _ in subtask_list:
                m = _re.match(r'^\[(.+?)\]', t.summary)
                if m:
                    parent_key = m.group(1)
                    parent_has_subtask[parent_key].append(t.key)
                    # find parent assignee from all_tickets
                    for at in all_tickets:
                        if at.key == parent_key:
                            assignee_subtask_parents[at.assignee_name or "Unassigned"].add(parent_key)

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
                # Show which tickets have at-risk subtasks
                parents_with_subtasks = assignee_subtask_parents.get(name, set())
                if parents_with_subtasks:
                    for pk in sorted(parents_with_subtasks):
                        sub_keys = ", ".join(f"`{s}`" for s in parent_has_subtask[pk])
                        url = f"{self.jira_base_url}/browse/{pk}"
                        chart_lines.append(f"  :warning: <{url}|{pk}> có subtask chưa update: {sub_keys}")
                chart_lines.append("")
            chart_text = "\n".join(chart_lines)

        # --- At-risk summary grouped by project → assignee ---
        import re as _re2
        from collections import defaultdict as _dd

        # parent_key → ticket object (from all_tickets, for fetching parent info)
        all_ticket_map = {t.key: t for t in (all_tickets or [])}

        # project → assignee → { email, main: [(t,a)], subtask_parents: {parent_key: [subtask]} }
        structure: dict = _dd(lambda: _dd(lambda: {"email": None, "main": [], "subtask_parents": _dd(list)}))

        for ticket, analysis in analyzed_tickets:
            project = ticket.key.split("-")[0]
            name = ticket.assignee_name or "Unassigned"
            structure[project][name]["email"] = ticket.assignee_email
            structure[project][name]["main"].append((ticket, analysis))

        for ticket, analysis in (subtasks or []):
            m = _re2.match(r'^\[(.+?)\]', ticket.summary)
            parent_key = m.group(1) if m else "Unknown"
            project = parent_key.split("-")[0]
            parent = all_ticket_map.get(parent_key)
            name = (parent.assignee_name if parent else None) or "Unassigned"
            email = (parent.assignee_email if parent else None)
            structure[project][name]["email"] = email
            structure[project][name]["subtask_parents"][parent_key].append(ticket)

        def _status_label(t):
            if t.is_blocked_flag:
                return "🔴 Blocked"
            if t.is_overdue:
                return "⏰ Overdue"
            return t.status

        def _group_by_status(ticket_list, base_url):
            by_status = _dd(list)
            for t in ticket_list:
                by_status[_status_label(t)].append(t)
            parts = []
            for label, tickets in by_status.items():
                keys = ", ".join(f"<{base_url}/browse/{t.key}|{t.key}>" for t in tickets)
                parts.append(f"{len(tickets)} {label} ({keys})")
            return parts

        summary_lines = [f":rotating_light: *At-Risk Summary — {today}*\n"]
        for project in sorted(structure.keys()):
            summary_lines.append(f"• *{project}*")
            for name, data in sorted(structure[project].items()):
                mention = self._resolve_mention(data["email"], name)
                main_tickets = [t for t, _ in data["main"]]
                sub_parents = data["subtask_parents"]
                # Combine main tickets + parent tickets (if not already in main)
                main_keys = {t.key for t in main_tickets}
                all_display_tickets = list(main_tickets)
                for parent_key in sorted(sub_parents.keys()):
                    parent = all_ticket_map.get(parent_key)
                    if parent and parent_key not in main_keys:
                        all_display_tickets.append(parent)
                total = len(all_display_tickets)
                status_parts = _group_by_status(all_display_tickets, self.jira_base_url)
                summary_lines.append(f"  • {mention} — {total} ticket(s): {', '.join(status_parts)}")
                # Subtasks under each parent
                for parent_key, subs in sorted(sub_parents.items()):
                    parent_url = f"{self.jira_base_url}/browse/{parent_key}"
                    sub_parts = _group_by_status(subs, self.jira_base_url)
                    summary_lines.append(f"    :arrow_right: <{parent_url}|{parent_key}>: {len(subs)} subtask(s) — {', '.join(sub_parts)}")
            summary_lines.append("")

        blocks = []
        for chunk in self._split_text("\n".join(summary_lines)):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
        if chart_text:
            blocks.append({"type": "divider"})
            for chunk in self._split_text(chart_text):
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

        self._dm_tpm(blocks, fallback="Daily Jira Summary")

    def send_tpm_report(self, analyzed_tickets: list, subtasks: list = None) -> None:
        """Post the detailed per-ticket report to the team channel."""
        today = date.today().strftime("%B %d, %Y")
        subtasks = subtasks or []
        total = len(analyzed_tickets) + len(subtasks)

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
                    "text": f"*{len(analyzed_tickets)} ticket(s)* and *{len(subtasks)} subtask(s)* flagged as stalled, blocked, or at risk.",
                },
            },
            {"type": "divider"},
        ]

        from collections import defaultdict as _dd
        import re as _re

        # Group by assignee
        by_assignee: dict = _dd(lambda: {"email": None, "tickets": [], "subtask_parents": _dd(list)})
        for ticket, analysis in analyzed_tickets:
            name = ticket.assignee_name or "Unassigned"
            by_assignee[name]["email"] = ticket.assignee_email
            by_assignee[name]["tickets"].append((ticket, analysis))
        for ticket, analysis in subtasks:
            m = _re.match(r'^\[(.+?)\]', ticket.summary)
            parent_key = m.group(1) if m else "Unknown"
            name = ticket.assignee_name or "Unassigned"
            by_assignee[name]["email"] = ticket.assignee_email
            by_assignee[name]["subtask_parents"][parent_key].append((ticket, analysis))

        for name, data in sorted(by_assignee.items()):
            mention = self._resolve_mention(data["email"], name)

            todo_tickets = [(t, a) for t, a in data["tickets"] if t.status.lower() == "to do" and not t.is_blocked_flag and not t.is_overdue]
            active_tickets = [(t, a) for t, a in data["tickets"] if (t, a) not in todo_tickets]

            todo_subs = []
            active_subs_by_parent: dict = _dd(list)
            for parent_key, items in data["subtask_parents"].items():
                for t, a in items:
                    if t.status.lower() == "to do" and not t.is_blocked_flag and not t.is_overdue:
                        todo_subs.append((t, a))
                    else:
                        active_subs_by_parent[parent_key].append((t, a))

            header_lines = [f":bust_in_silhouette: *{mention}*"]
            todo_parts = []
            if todo_tickets:
                todo_keys = ", ".join(f"<{self.jira_base_url}/browse/{t.key}|{t.key}>" for t, _ in todo_tickets)
                todo_parts.append(f"{len(todo_tickets)} ticket(s) To Do ({todo_keys})")
            if todo_subs:
                todo_keys = ", ".join(f"<{self.jira_base_url}/browse/{t.key}|{t.key}>" for t, _ in todo_subs)
                todo_parts.append(f"{len(todo_subs)} subtask(s) To Do ({todo_keys})")
            if todo_parts:
                header_lines.append(f":white_circle: {', '.join(todo_parts)} — Có cần cập nhật không?")

            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(header_lines)}})

            for ticket, analysis in active_tickets:
                blocks.extend(self._ticket_blocks(ticket, analysis))

            for parent_key, items in sorted(active_subs_by_parent.items()):
                parent_url = f"{self.jira_base_url}/browse/{parent_key}"
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":small_blue_diamond: Subtasks of <{parent_url}|{parent_key}>"},
                })
                for ticket, analysis in items:
                    blocks.extend(self._ticket_blocks(ticket, analysis))

            blocks.append({"type": "divider"})

        if self.dry_run:
            import json
            logger.info("[DRY RUN] Channel report blocks:\n%s", json.dumps(blocks, indent=2))
            return
        # Slack limit: 50 blocks per message
        for i in range(0, len(blocks), 50):
            try:
                self.client.chat_postMessage(
                    channel=self.team_channel_id,
                    blocks=blocks[i:i+50],
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
                        f"{icon} *<{url}|{ticket.key}>* — {ticket.summary.split('] ', 1)[-1] if ticket.summary.startswith('[') else ticket.summary}\n"
                        f"*Assignee:* {mention}   *Status:* {ticket.status}\n"
                        f":arrow_right: {analysis.recommended_action}"
                    ),
                },
            },
        ]

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _split_text(self, text: str, limit: int = 2900) -> list:
        """Split text into chunks that fit within Slack's block text limit."""
        if len(text) <= limit:
            return [text]
        chunks = []
        lines = text.split("\n")
        current = []
        current_len = 0
        for line in lines:
            if current_len + len(line) + 1 > limit:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

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
