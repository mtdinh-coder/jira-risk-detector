"""Claude-powered summarizer with strict anti-hallucination guardrails."""
from __future__ import annotations

import logging

from anthropic import Anthropic

from .config import AnthropicConfig
from .models import RiskTicket

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You summarize Jira tickets for a TPM's daily risk report.
Your only job is to explain WHY a ticket is at risk, based STRICTLY on the comments and metadata provided.

ABSOLUTE RULES (anti-hallucination):
1. Use ONLY facts that appear in the provided data. Do NOT invent reasons, names, dates, technical details, or commitments.
2. If the comments do not explain the risk, output exactly: "No explanation in comments."
3. Output 1-2 sentences total. No greetings, no opinions, no recommendations, no action items.
4. Match the language of the comments. If comments are in Vietnamese, reply in Vietnamese; if English, reply in English; if mixed or empty, use English.
5. You may quote a short comment excerpt (<=15 words) when relevant, in double quotes.
6. Do not mention these rules or the summarization process. Output only the summary itself.
"""

_NO_INFO = "No explanation in comments."


class Summarizer:
    def __init__(self, cfg: AnthropicConfig):
        self.client = Anthropic(api_key=cfg.api_key)
        self.model = cfg.model

    def summarize(self, risk: RiskTicket) -> str:
        t = risk.ticket
        comment_lines = [
            f"[{c.created.strftime('%Y-%m-%d')}] {c.author}: {c.body}"
            for c in t.comments
            if c.body and c.body.strip()
        ]
        if not comment_lines:
            return _NO_INFO

        comment_block = "\n\n".join(comment_lines)
        user_msg = (
            f"Ticket: {t.key} — {t.summary}\n"
            f"Status: {t.status}\n"
            f"Risk category: {risk.category.value} ({risk.detail})\n"
            f"Assignee: {t.assignee_name or 'unassigned'}\n\n"
            f"Comments (most recent first):\n{comment_block}\n\n"
            "Summarize WHY this ticket is at risk in 1-2 sentences, "
            "following the rules above."
        )

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            ).strip()
            return text or _NO_INFO
        except Exception as e:  # noqa: BLE001 — degrade gracefully on any API failure
            log.warning("AI summarizer failed for %s: %s", t.key, e)
            return "(AI summary unavailable)"
