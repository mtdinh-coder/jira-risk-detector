# Jira Risk Detector Agent — Phase 1

Daily automated check of a single Jira project. Detects blocked / overdue / stalled / due-soon tickets, asks Claude to summarize the *real reason* from the comments (no hallucination), and sends a structured report to the TPM via Slack DM plus a public reminder that tags the dev/QA owner.

## Architecture

```
                ┌─────────────┐
                │ Task Schdlr │ daily 9:00
                └──────┬──────┘
                       ▼
                  src/main.py
                       │
        ┌──────────────┼─────────────────┐
        ▼              ▼                 ▼
   JiraClient    RiskDetector       Summarizer
   (REST v3)    (4 rules + sev.)   (Claude, anti-hallucination)
        │                                 │
        └──────────────┬──────────────────┘
                       ▼
                 SlackNotifier
                  ├── DM → TPM (full report)
                  └── #channel → tag dev/QA
```

| Module | Responsibility |
|---|---|
| [src/config.py](src/config.py) | Load + validate `.env` config (pydantic) |
| [src/jira_client.py](src/jira_client.py) | Read-only Jira REST v3 + ADF text extraction |
| [src/risk_detector.py](src/risk_detector.py) | JQL builder + 4-rule classifier with severity ordering |
| [src/ai_summarizer.py](src/ai_summarizer.py) | Claude summarization with strict anti-hallucination prompt |
| [src/slack_notifier.py](src/slack_notifier.py) | Slack Web API wrapper (DM + post) |
| [src/formatters.py](src/formatters.py) | Slack Block Kit message templates |
| [src/main.py](src/main.py) | Orchestrator entry point |

## Prerequisites

- **Python 3.11+** on PATH (`python --version`)
- **Jira API token** — generate at https://id.atlassian.com/manage-profile/security/api-tokens
- **Slack Bot token** with scopes: `chat:write`, `im:write`, `users:read`, `users:read.email`
- **Anthropic API key** — https://console.anthropic.com

## Setup

```powershell
cd C:\Users\mtdinh\jira-risk-detector
.\scripts\setup.ps1
notepad .env       # fill in credentials
```

The setup script creates `.venv`, installs dependencies, and seeds `.env` from the example.

### Required .env values

| Variable | Notes |
|---|---|
| `JIRA_BASE_URL` | e.g. `https://nvidia.atlassian.net` |
| `JIRA_EMAIL` | Account that owns the API token |
| `JIRA_API_TOKEN` | The generated token, not your password |
| `JIRA_PROJECT_KEY` | The prefix in ticket IDs (e.g. `ABC` for `ABC-123`) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_TEAM_CHANNEL_ID` | Channel **ID** (not name), e.g. `C0123456789`. Right-click channel → View details → Channel ID. |
| `SLACK_TPM_EMAIL` | TPM's Slack email. Defaults to `JIRA_EMAIL`. |

### Optional tuning

| Variable | Default | Effect |
|---|---|---|
| `STALLED_DAYS` | 3 | In-Progress with no update for ≥ N days → Stalled |
| `DUE_SOON_DAYS` | 2 | Due within N days → Due Soon |
| `COMMENTS_FOR_SUMMARY` | 8 | Most-recent N comments fed to AI |
| `JIRA_EXTRA_JQL` | "" | Appended with AND, e.g. `fixVersion = "2026.Q2"` |
| `JIRA_QA_FIELD` | "" | Custom field id for QA owner (e.g. `customfield_10100`) |
| `DRY_RUN` | false | Print messages to console instead of sending |

## Test it locally

```powershell
# 1. Set DRY_RUN=true in .env
# 2. Run once
.\scripts\run.ps1
```

Run unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

## Schedule for 9 AM daily

```powershell
.\scripts\setup_scheduler.ps1
```

This registers a Windows Scheduled Task (`JiraRiskDetector`) that runs at 9:00 AM every day. The task uses `StartWhenAvailable`, so if your laptop is off at 9 AM it will run when you next sign in.

Useful follow-ups:

```powershell
Start-ScheduledTask -TaskName "JiraRiskDetector"             # run now
Get-ScheduledTask -TaskName "JiraRiskDetector" | Get-ScheduledTaskInfo
Unregister-ScheduledTask -TaskName "JiraRiskDetector" -Confirm:$false
```

Logs land in `logs/run-YYYY-MM-DD.log`.

## Risk classification rules (Phase 1)

A ticket is flagged if **any** of the following holds (highest-severity wins, ordered top-to-bottom):

1. **Blocked** — `status` contains "Block" *or* `labels` contains `blocker`
2. **Overdue** — `duedate` in the past and not Done
3. **Stalled** — status In Progress and `updated` ≥ `STALLED_DAYS` days ago
4. **Due Soon** — `duedate` within next `DUE_SOON_DAYS` days and not Done

The agent only reads — it never mutates Jira tickets.

## How the AI avoids hallucinating

The system prompt in [src/ai_summarizer.py](src/ai_summarizer.py) enforces:

- Use ONLY facts present in the comments / metadata
- If the comments don't explain the risk, output exactly `"No explanation in comments."` — never speculate
- Cap at 1–2 sentences
- Match the comment language (Vietnamese / English)
- May quote a short comment excerpt (≤15 words)

Combined with feeding only the actual comment bodies (no inferred context), this keeps output grounded.

## Slack message format

**TPM DM** (full report, every day):
```
*Daily Jira risk check — `ABC` — 2026-05-07*
Found *3* at-risk ticket(s):  🚫 Blocked: 1  ·  🟡 Stalled: 2
─────────────────────
🚫 *<https://...|ABC-101>*  ·  *Blocked*  ·  _status: Blocked_
*Title:* Migrate billing service to v2
*Owner:* Alice Nguyen  ·  *Priority:* High
*Why:* Waiting on infra team to provision the new RDS instance.
─────────────────────
```

**Team channel** (only when there are risks, tags owners):
```
🔍 *Daily Jira check — `ABC` — 2026-05-07* — *3* ticket(s) need attention. Owners please update:
─────────────────────
🚫 *<...|ABC-101>* — Migrate billing service to v2  ·  _status: Blocked_  →  @alice @qa-bob
🟡 *<...|ABC-115>* — Add retry to webhook handler  ·  _no update in 5d_  →  @charlie
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing required env var` | Edit `.env` — make sure no leading spaces around `=` |
| `Slack user lookup failed: users_not_found` | The TPM's Slack email differs from `JIRA_EMAIL`. Set `SLACK_TPM_EMAIL` explicitly. |
| `chat_postMessage: not_in_channel` | Invite the bot: `/invite @your-bot-name` in the team channel. |
| `401 Unauthorized` from Jira | API token expired/typo, or email mismatch with token owner. |
| AI summary is `(AI summary unavailable)` | Check `ANTHROPIC_API_KEY` validity and quota. The pipeline still posts the report. |
| QA name not appearing | Set `JIRA_QA_FIELD=customfield_XXXXX`. Find the id at `/rest/api/3/field` on your Jira site. |

## Phase 2 ideas (out of scope for now)

- Track issuelinks (`is blocked by`) for true dependency-based blocked detection
- Per-team channel routing (one project, multiple sub-teams)
- Trend metrics (week-over-week blocker count) posted to a dashboard channel
- Auto-draft follow-up Jira comment when a ticket has been stalled 7+ days (write scope)
