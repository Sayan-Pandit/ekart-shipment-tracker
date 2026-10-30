# 📦 Ekart Shipment Tracker & Discord Bot

[![CI Test Suite](https://github.com/Sayan-Pandit/ekart-shipment-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Sayan-Pandit/ekart-shipment-tracker/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/docs-system_architecture-orange.svg)](docs/SYSTEM_DOCUMENTATION.md)

An enterprise-grade, production-ready Ekart Logistics shipment tracking platform featuring a **multi-threaded background server daemon**, **dual-channel automated notifications** (Email via SMTP + Discord via Bot & Webhook), a **Discord Bot with slash commands**, and a **rich terminal interface**.

---

## 🏗️ Architecture & Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Ekart Logistics Network                │
│                 (Reverse-Engineered v2 Scraper)             │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Polling Every 120s)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Ekart Tracker Server Daemon                 │
│   • Multi-Threaded Polling Scheduler                        │
│   • REST API Engine (Flask / Gunicorn)                      │
│   • SQLite Concurrency (WAL Mode + Thread-Safe Connection)  │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼ (Status Changed)             ▼ (Commands & Queries)
┌──────────────────────────────┐ ┌────────────────────────────┐
│      Dual Notifications      │ │         Interfaces         │
│  • Email (SMTP Rich HTML)    │ │  • Discord Bot (Slash & !) │
│  • Discord Bot (DM & Channel)│ │  • Terminal CLI / TUI      │
│  • Webhooks (Discord/Telegram)│ │  • REST API (JSON)         │
└──────────────────────────────┘ └────────────────────────────┘
```

### 1. Reverse-Engineered Tracking Mechanism
* **Session Handshake**: Automatically resolves Express session cookies (`session`, `session.sig`, `ab`, `epoctime`).
* **CSRF Token Parser**: Extracts the dynamic CSRF token from `<meta name="csrf-token" content="...">`.
* **v2 Endpoint**: Issues POST requests to `/ekartlogistics-web-routes-api/ekartlogistics-web-proxy/trackings/v2` with `X-User-Agent: EKCL/website/1`.
* **Self-Healing Retries**: Exponential backoff adapter with auto-renewal on HTTP 205 / `EBADCSRFTOKEN` token expiration.

---

## 🤖 Discord Bot Features

The bot connects via Discord Gateway and provides real-time shipment updates directly in server channels or **private DMs**:

### Commands Reference

| Slash Command | Prefix Command | Description |
|---|---|---|
| `/track <id> [label] [sim]` | `!track <id> [label]` | Start tracking a package. Automatically links updates to your DM or channel. |
| `/status <id>` | `!status <id>` | View current live status, delivery ETA, nearest hub, and journey timeline. |
| `/list` | `!list` | Display all actively tracked packages with live badges. |
| `/simulate <id>` | `!simulate <id>` | Step a simulated package to the next stage to test alerts. |
| `/remove <id>` | `!remove <id>` | Remove a package from the continuous monitoring pool. |
| `/notifytest` | `!notifytest` | Send a sample notification card to test channel integration. |
| `/help` | `!help` | View command guide and usage tips. |

---

## ⚡ Production Deployment Options

### Option A: Render (Cloud Hosting)
The repository is pre-configured with `render.yaml` and `Procfile`:
1. Push this repository to GitHub.
2. In [Render Dashboard](https://dashboard.render.com), click **New + ➔ Web Service** and connect your repository.
3. Configure the environment variables:
   * `DISCORD_BOT_TOKEN`: Your Discord Bot token
   * `DISCORD_USER_ID`: Your Discord User ID (for private DM alerts)
   * `POLL_INTERVAL_SECONDS`: `120`
4. Deploy! To keep the free tier awake 24/7, set a free monitor on [UptimeRobot](https://uptimerobot.com) to ping `https://your-service.onrender.com/health` every 10 minutes.

### Option B: Docker & Docker Compose
A production `Dockerfile` with non-root security and healthcheck is included:
```bash
# Build and run with Docker Compose (with persistent volume)
docker compose up -d

# Check logs
docker compose logs -f

# Check container health
docker ps
```

### Option C: Local / VPS Daemon (Linux / Windows)
```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .

# Run the unified server + Discord bot
python run.py
```

---

## 💻 Terminal CLI Commands

```powershell
# 1. Query live status of any Ekart package immediately
python -m ekart_tracker.cli check FMPC0279658213

# 2. Add package to background tracking pool
python -m ekart_tracker.cli add FMPC0279658213 --label "Laptop"

# 3. Add demo package for testing
python -m ekart_tracker.cli add SIM-WATCH --label "Smartwatch" --simulate

# 4. View formatted shipment list table
python -m ekart_tracker.cli list

# 5. View complete journey milestone tree
python -m ekart_tracker.cli info SIM-WATCH

# 6. Check background server status
python -m ekart_tracker.cli server status

# 7. Launch auto-refreshing live terminal monitor
python -m ekart_tracker.cli dashboard

# 8. Interactive terminal menu
python -m ekart_tracker
```

---

## 📡 REST API Reference

The server exposes standard JSON REST endpoints:

* `GET /`: Service overview, version, uptime, and bot status.
* `GET /health`: Healthcheck endpoint for load balancers and container monitors.
* `GET /api/status`: Detailed system status, notification channel health, and tracking counts.
* `GET /api/shipments`: List all tracked packages.
* `POST /api/shipments`: Add new package to tracking (`{"tracking_id": "...", "label": "..."}`).
* `GET /api/shipments/<id>`: Get journey details and milestone array for a package.
* `DELETE /api/shipments/<id>`: Remove package from tracking.
* `POST /api/shipments/<id>/refresh`: Force an immediate live refresh.
* `POST /api/shipments/<id>/simulate`: Advance a simulated package to the next stage.
* `GET /api/notifications`: View recent notification logs.

---

## 🧪 Automated Testing

Run the test suite across tracking, SQLite storage, notification dispatchers, and REST endpoints:
```bash
python -m unittest discover -s tests
```
All 27 unit tests run in ~2 seconds with 100% pass rate.
