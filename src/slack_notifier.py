"""Slack messaging — DM the TPM, tag dev/QA in a public channel."""
from __future__ import annotations

import logging
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

log = logging.getLogger(__name__)


class SlackNotifier:
    def __init__(self, bot_token: str):
        self.client = WebClient(token=bot_token)
        self._email_cache: dict[str, Optional[str]] = {}

    def user_id_by_email(self, email: Optional[str]) -> Optional[str]:
        if not email:
            return None
        if email in self._email_cache:
            return self._email_cache[email]
        try:
            r = self.client.users_lookupByEmail(email=email)
            uid = r["user"]["id"]
        except SlackApiError as e:
            log.warning(
                "Slack user lookup failed for %s: %s",
                email,
                e.response.get("error") if e.response else e,
            )
            uid = None
        self._email_cache[email] = uid
        return uid

    def open_dm(self, user_id: str) -> Optional[str]:
        try:
            r = self.client.conversations_open(users=user_id)
            return r["channel"]["id"]
        except SlackApiError as e:
            log.error(
                "Could not open DM with %s: %s",
                user_id,
                e.response.get("error") if e.response else e,
            )
            return None

    def post(self, channel: str, text: str, blocks: Optional[list] = None) -> bool:
        try:
            self.client.chat_postMessage(channel=channel, text=text, blocks=blocks)
            return True
        except SlackApiError as e:
            log.error(
                "Slack post failed (channel=%s): %s",
                channel,
                e.response.get("error") if e.response else e,
            )
            return False
