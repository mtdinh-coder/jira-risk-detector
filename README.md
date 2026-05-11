# Jira Risk Detector

Tự động quét Jira mỗi thứ 2 và thứ 5 lúc 9h sáng (ICT). Phát hiện ticket stalled/blocked/overdue và gửi báo cáo lên Slack.

## Tính năng

- Quét **main tickets** và **subtasks** trong sprint đang chạy
- Gửi **DM cho TPM**: At-Risk Summary (theo project → assignee) + Workload chart
- Gửi **report lên channel**: nhóm theo assignee, ticket To Do chỉ ghi số lượng
- Gửi **nudge reminder** cho ticket chưa update >= `NUDGE_DAYS` ngày làm việc
- Gửi **all-clear** khi không có ticket nào at-risk
- Tính **ngày làm việc** (bỏ qua thứ 7, CN)
- Hỗ trợ nhiều project (ví dụ: `TTS,ASR`)
- Loại trừ assignee cụ thể

## Cấu trúc

```
jira-risk-detector/
├── agent.py           # Orchestrator chính
├── jira_client.py     # Jira REST API v2 (Server PAT auth)
├── risk_analyzer.py   # Rule-based risk analysis
├── slack_notifier.py  # Slack Block Kit messages
├── config.py          # Config từ environment variables
├── scheduler.py       # Chạy 1 lần (--once) hoặc loop
└── .github/workflows/
    └── daily-scan.yml # GitHub Actions: thứ 2 & thứ 5 lúc 9h sáng ICT
```

## Setup

### 1. Clone repo

```powershell
git clone https://github.com/mtdinh-coder/jira-risk-detector.git
cd jira-risk-detector
pip install -r requirements.txt
```

### 2. Tạo file `.env`

```env
# Jira
JIRA_BASE_URL=https://jirasw.nvidia.com
JIRA_EMAIL=your-username
JIRA_API_TOKEN=your-jira-pat-token
JIRA_PROJECT_KEY=TTS,ASR
JIRA_EXCLUDE_ASSIGNEES=Jayda Ritchie

# Risk thresholds
STALLED_DAYS=3
NUDGE_DAYS=2
DUE_SOON_DAYS=2
COMMENTS_FOR_SUMMARY=8

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_TEAM_CHANNEL_ID=C0123456789
SLACK_TPM_EMAIL=your-email@nvidia.com

# Behavior
DRY_RUN=false
LOG_LEVEL=INFO
```

### 3. Chạy thử (không gửi Slack)

```powershell
$env:DRY_RUN="true"; python scheduler.py --once
```

### 4. Chạy thật

```powershell
$env:DRY_RUN="false"; python scheduler.py --once
```

## GitHub Actions

Workflow chạy tự động **thứ 2 và thứ 5 lúc 9h sáng ICT** (2:00 AM UTC).

Thêm các secrets sau vào **Settings → Secrets → Actions**:

| Secret | Mô tả |
|---|---|
| `JIRA_BASE_URL` | URL Jira server |
| `JIRA_EMAIL` | Username Jira |
| `JIRA_API_TOKEN` | Personal Access Token |
| `JIRA_PROJECT_KEY` | Ví dụ: `TTS,ASR` |
| `JIRA_EXCLUDE_ASSIGNEES` | Tên assignee cần bỏ qua |
| `STALLED_DAYS` | Số ngày làm việc không update → stalled (mặc định: 3) |
| `NUDGE_DAYS` | Số ngày làm việc không update → nhắc nhở (mặc định: 2) |
| `DUE_SOON_DAYS` | Số ngày còn lại đến deadline → cảnh báo (mặc định: 2) |
| `COMMENTS_FOR_SUMMARY` | Số comment gần nhất để phân tích (mặc định: 8) |
| `SLACK_BOT_TOKEN` | `xoxb-...` |
| `SLACK_TEAM_CHANNEL_ID` | Channel ID (không phải tên) |
| `SLACK_TPM_EMAIL` | Email TPM nhận DM |

**Tắt/bật workflow**: Actions → Daily Scan → `...` → Disable/Enable workflow

## Logic phát hiện rủi ro

Ticket bị đánh dấu at-risk nếu thoả **một trong các điều kiện**:

| Điều kiện | Mô tả |
|---|---|
| **Blocked** | Status = "Blocked" hoặc label có "blocked"/"impediment" |
| **Overdue** | Có due date và đã quá hạn |
| **Stalled** | Không update >= `STALLED_DAYS` ngày làm việc |
| **Due Soon** | Còn <= `DUE_SOON_DAYS` ngày đến deadline |

> Ngày làm việc = thứ 2 đến thứ 6, không tính thứ 7 và CN.

## Slack scopes cần thiết

- `chat:write`
- `im:write`
- `users:read`
- `users:read.email`

## Troubleshooting

| Lỗi | Cách xử lý |
|---|---|
| `401 Unauthorized` | Token Jira sai hoặc hết hạn — tạo lại PAT |
| `not_authed` | Slack token sai — kiểm tra `SLACK_BOT_TOKEN` |
| `missing_scope` | Thêm scope còn thiếu vào Slack app và reinstall |
| `channel_not_found` | Dùng Channel ID (không phải tên), invite bot vào channel |
| `invalid_blocks` | Text block quá 3000 ký tự — đã được xử lý tự động |
| `sprint in openSprints()` lỗi 400 | Jira server không hỗ trợ — xoá dòng đó trong `jira_client.py` |
