# Shift Roster WhatsApp Notification System

Connects **etimetracklite** to **Pingerbot WhatsApp API** to automatically
notify employees of their daily shift and send a manager summary report.

## Architecture

```
etimetracklite (SQL or REST API)
        │
        ▼
  Roster Processor
   ├── Personal shift reminder → each employee (WhatsApp)
   └── Full daily summary     → manager phones (WhatsApp)
        │
        ▼
  Pingerbot WhatsApp API
```

## Setup

```bash
cd shift_roster
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
```

## Configuration (`.env`)

| Variable | Description |
|---|---|
| `ETL_MODE` | `sql` (direct DB) or `api` (REST) |
| `ETL_DB_HOST/PORT/NAME/USER/PASSWORD` | SQL credentials |
| `ETL_API_BASE_URL / ETL_API_KEY` | API-mode credentials |
| `PINGERBOT_API_URL` | Your Pingerbot send endpoint |
| `PINGERBOT_API_TOKEN` | Pingerbot bearer token |
| `PINGERBOT_INSTANCE_ID` | (optional) Pingerbot instance/session ID |
| `SEND_TIME` | Daily send time e.g. `07:00` |
| `SEND_DAY_OFFSET` | `0` = today, `1` = tomorrow's roster |
| `MANAGER_PHONES` | Comma-separated manager numbers e.g. `+919999999999` |

## Usage

```bash
# Preview messages without sending
python main.py run --dry-run

# Send today's roster now
python main.py run

# Send for a specific date
python main.py run --date 2024-06-15

# Start daily scheduler daemon
python main.py schedule-daemon
```

## etimetracklite SQL Tables Used

| Table | Purpose |
|---|---|
| `tbl_roster_schedule` | Daily roster assignments |
| `tbl_employee` | Employee name, mobile, department |
| `tbl_shift` | Shift code, name, in/out time |

> If your etimetracklite uses different table/column names, edit
> `src/etimetracklite/sql_connector.py` — the SQL query is clearly labelled.

## Pingerbot API

The client posts to `PINGERBOT_API_URL` with:

```json
{
  "phone":       "919876543210",
  "message":     "*Shift Reminder* ...",
  "instance_id": "optional"
}
```

Adjust `src/whatsapp/pingerbot.py` if your endpoint expects a different payload shape.

## Running as a Service (systemd)

```ini
[Unit]
Description=Shift Roster WhatsApp Notifier

[Service]
WorkingDirectory=/opt/shift_roster
ExecStart=/usr/bin/python3 main.py schedule-daemon
EnvironmentFile=/opt/shift_roster/.env
Restart=always

[Install]
WantedBy=multi-user.target
```
