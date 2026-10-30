# 📦 Ekart Shipment Tracker & Discord Bot

An enterprise-grade Ekart Logistics package tracker featuring a **background server daemon**, **dual-channel notifications** (Email + Discord Bot / Webhook), and an interactive **rich terminal interface**.

---

## 🔍 Tracking Mechanism Inspection

The Ekart Logistics tracking mechanism was reverse-engineered by inspecting the modern web application bundle on `https://ekartlogistics.com`:

1. **CSRF & Session Bootstrap**:
   - The Ekart frontend establishes an Express session (`session`, `session.sig`, `ab`, `epoctime` cookies).
   - An active CSRF token is issued in the HTML `<meta name="csrf-token" content="...">` tag.
2. **Modern Tracking Endpoint**:
   - **URL**: `POST https://ekartlogistics.com/ekartlogistics-web-routes-api/ekartlogistics-web-proxy/trackings/v2`
   - **Headers**:
     - `User-Agent`: Chrome User Agent
     - `X-User-Agent`: `<User-Agent> EKCL/website/1`
     - `csrf-token`: Extracted CSRF token
     - `Content-Type`: `application/json`
     - `Origin`: `https://ekartlogistics.com`
     - `Referer`: `https://ekartlogistics.com/shipmenttrack/<trackingId>`
   - **Payload**: `{"tracking_ids": "<TRACKING_ID>"}`
   - **Response Format**:
     ```json
     {
       "FMPC0279658213": {
         "shipmentTrackingDetails": [
           {
             "date": 1698765432000,
             "city": "Bengaluru",
             "statusDetails": "Received at Facility"
           }
         ],
         "expectedDeliveryDate": 1698888000000,
         "faShipment": true,
         "reachedNearestHub": true
       }
     }
     ```
3. **Resilience & Auto-Recovery**:
   - Handles CSRF expiration (`HTTP 205` / `EBADCSRFTOKEN`) by automatically renewing tokens and retrying.
   - Built-in simulation and demo engine for testing tracking transitions, alerts, and bot triggers offline.

---

## ⚙️ Architecture & Choices

- **Platform: Server Daemon**
  - Continuous multi-threaded background polling worker checking active packages.
  - Flask REST API (`http://127.0.0.1:5050`) for management, query, simulation, and notification triggers.
  - SQLite persistence (`data/tracker.db`) for tracking states, milestone history, and notification logs.
- **Notifications: Both (Email + Discord)**
  - **Channel 1 (Email)**: Professional HTML emails with status color banners, badges, and milestone journey tables, plus plain-text fallback.
  - **Channel 2 (Discord)**: Interactive Discord Bot and Webhook with rich embeds, dynamic status progress bars (`[🟩🟩🟩⬜⬜] 60%`), and channel announcements.
- **Interface: Terminal**
  - Built with `Rich` and `Click`.
  - Color-coded shipment tables, timeline trees, live dashboard monitor, and interactive keyboard menu.

---

## 🤖 Discord Bot Capabilities

The tracker includes a full Discord Bot (`discord.py`) supporting both **Slash Commands** and **Prefix Commands** (`!track`, `!status`, etc.):

| Slash Command | Prefix Command | Description |
|---|---|---|
| `/track <id> [label] [sim]` | `!track <id> [label]` | Start tracking a package in the monitoring pool |
| `/status <id>` | `!status <id>` | Inspect live status, ETA, and journey timeline |
| `/list` | `!list` | Display all currently tracked shipments |
| `/simulate <id>` | `!simulate <id>` | Advance simulated package to next stage to test alerts |
| `/remove <id>` | `!remove <id>` | Stop tracking and remove a package |
| `/notifytest` | `!notifytest` | Dispatch a sample alert embed to test channel integration |
| `/help` | `!help` | View command guide |

Whenever a package status updates, the server automatically posts an alert embed into the configured Discord channel and sends an email notification.

---

## 🚀 Quick Start

### 1. Installation
```powershell
# Clone or navigate to the directory
cd "d:\Shipment Tracker"

# Install dependencies
python -m pip install -r requirements.txt
python -m pip install -e .
```

### 2. Configuration (`.env`)
Copy `.env.example` to `.env`:
```env
# Server
SERVER_HOST=127.0.0.1
SERVER_PORT=5050
POLL_INTERVAL_SECONDS=120

# Notifications: Channel 1 (Email)
NOTIFY_EMAIL_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=Ekart Tracker <your_email@gmail.com>
EMAIL_TO=recipient@example.com

# Notifications: Channel 2 (Discord Bot & Webhook)
NOTIFY_WEBHOOK_ENABLED=true
DISCORD_BOT_ENABLED=true
DISCORD_BOT_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_ID=your_discord_channel_id_here
DISCORD_PREFIX=!

# Optional Discord Webhook fallback
WEBHOOK_URL=https://discord.com/api/webhooks/...
```
*(Note: If credentials are not configured, the system operates in Dry-Run simulation mode, allowing complete testing without failure.)*

---

## 💻 Terminal CLI Commands

### Server Daemon Management
```powershell
# Check background server health & status
python -m ekart_tracker.cli server status

# Start server daemon (foreground)
python -m ekart_tracker.cli server start

# Start server in background
python -m ekart_tracker.cli server start --daemon

# Stop server daemon
python -m ekart_tracker.cli server stop
```

### Tracking Packages
```powershell
# Query live Ekart portal immediately without saving
python -m ekart_tracker.cli check FMPC0279658213

# Add package to background tracking pool
python -m ekart_tracker.cli add FMPC0279658213 --label "Flipkart Electronics"

# Add a simulated demo package
python -m ekart_tracker.cli add SIM-LAPTOP --label "Gaming Laptop" --simulate

# List tracked packages with status badges
python -m ekart_tracker.cli list

# View detailed journey timeline tree
python -m ekart_tracker.cli info SIM-LAPTOP

# Remove a package
python -m ekart_tracker.cli remove SIM-LAPTOP
```

### Discord Bot Controls
```powershell
# Check Discord Bot configuration status
python -m ekart_tracker.cli bot status

# Launch the Discord Bot
python -m ekart_tracker.cli bot start
```

### Testing Notifications & Milestones
```powershell
# Advance a simulated package to test dual notifications (Email + Discord)
python -m ekart_tracker.cli simulate SIM-LAPTOP

# Trigger immediate test notification to both channels
python -m ekart_tracker.cli notify-test

# View notification dispatch history
python -m ekart_tracker.cli notifications
```

### Interactive Live Dashboard & Menu
```powershell
# Launch auto-refreshing live terminal monitor
python -m ekart_tracker.cli dashboard

# Launch interactive terminal navigation menu
python -m ekart_tracker.cli menu
# or simply:
python -m ekart_tracker
```

---

## 🧪 Automated Testing
Run the complete test suite:
```powershell
python -m unittest discover -s tests
```
All 17 tests covering tracking inspection, parsing, storage, dual-channel notifications, and REST endpoints pass with 100% success.

