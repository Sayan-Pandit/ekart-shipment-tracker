# 🚀 System Improvements & Engineering Log

This document provides a comprehensive audit of all improvements made to the **Ekart Shipment Tracker & Discord Bot**, detailing **what** was implemented, **why** it was necessary, and the **impact** on reliability, security, performance, and user experience.

---

## 📋 Summary of Improvements

| Category | Improvement | Primary Benefit |
|---|---|---|
| **Database & Concurrency** | SQLite Write-Ahead Logging (`WAL`) Mode & Composite Indexes | Eliminates database locks across multi-threaded operations. |
| **Network & Scraping** | Exponential Backoff Adapter & Short TTL In-Memory Cache | Resilient to transient network drops; reduces Ekart server load. |
| **Security & Privacy** | Credential Masking in API/Logs & Tracking ID Sanitization | Prevents secret leakage and rejects malformed/malicious inputs. |
| **Discord Bot UX** | One-Click Web Portal Link Buttons & `/stats` Command | Instant 1-click verification on Ekart site; real-time system visibility. |
| **Auto-Notifications** | Per-Shipment Notification Target Routing (`notify_target`) | Automatically replies to the exact DM or channel where requested. |
| **Code Modernization** | Timezone-Aware UTC Standard (`datetime.now(timezone.utc)`) | Removes Python 3.12+ deprecation warnings; ensures accurate timekeeping. |
| **Cloud & DevOps** | Production Dockerfile, Docker Compose & GitHub Actions CI | 1-command portable deployment and automated testing across Python versions. |
| **Observability** | Centralized System Metrics (`/api/stats` and `!stats`) | Fast real-time insight into active packages, delivery counts, and alerts. |

---

## 🔍 Detailed Component Improvements

### 1. Database Concurrency & Storage Optimization
* **File Modified**: [`ekart_tracker/storage.py`](file:///d:/Shipment%20Tracker/ekart_tracker/storage.py)
* **What was done**:
  * Configured SQLite to run with `PRAGMA journal_mode=WAL;` (Write-Ahead Logging) and `PRAGMA synchronous=NORMAL;`.
  * Added `check_same_thread=False` and extended the busy timeout to `30.0` seconds.
  * Added composite indexes:
    * `CREATE INDEX idx_shipments_active ON shipments (is_active, last_checked_at);`
    * `CREATE INDEX idx_notifications_tid ON notifications (tracking_id, created_at);`
  * Added storage maintenance methods: `get_stats()` and `cleanup_old_notifications()`.
* **Why it was done**:
  * Default SQLite locks the entire database during writes. When the Flask REST API, the background polling thread, and the Discord Bot thread simultaneously accessed the database, lock contention could trigger `sqlite3.OperationalError: database is locked`.
  * WAL mode allows concurrent readers and writers without blocking each other.
  * Adding indexes ensures polling queries remain $O(1)$ fast even when hundreds of packages are tracked over time.

---

### 2. Network Resilience & In-Memory TTL Caching
* **Files Modified**: [`ekart_tracker/tracker.py`](file:///d:/Shipment%20Tracker/ekart_tracker/tracker.py), [`ekart_tracker/config.py`](file:///d:/Shipment%20Tracker/ekart_tracker/config.py)
* **What was done**:
  * Embedded `urllib3.util.retry.Retry` with an `HTTPAdapter` inside `requests.Session` with exponential backoff on HTTP status codes `500`, `502`, `503`, and `504`.
  * Implemented an in-memory TTL query cache (30 seconds configurable via `CACHE_TTL_SECONDS`).
  * Added batch query support (`track_batch(tracking_ids)`).
* **Why it was done**:
  * External logistics scrapers face intermittent network drops, DNS blips, and gateway timeouts. Exponential backoff automatically recovers without throwing errors to end-users.
  * Rapid duplicate commands (e.g. multiple users querying `/status` within seconds) would hammer the Ekart portal and risk IP rate-limiting. Caching shields the external API while returning instant responses.

---

### 3. Security Hardening & Input Sanitization
* **Files Modified**: [`ekart_tracker/models.py`](file:///d:/Shipment%20Tracker/ekart_tracker/models.py), [`ekart_tracker/config.py`](file:///d:/Shipment%20Tracker/ekart_tracker/config.py), [`ekart_tracker/server.py`](file:///d:/Shipment%20Tracker/ekart_tracker/server.py)
* **What was done**:
  * Added `sanitize_tracking_id(tracking_id: str)`: Strips whitespace, forces uppercase, strips illegal characters via regex (`[^A-Z0-9\-_]`), and enforces strict length boundaries (3–40 characters).
  * Added `config.to_safe_dict()`: Masks sensitive secrets (bot tokens, SMTP passwords, webhook URLs, user IDs) before exposing them in `/api/status` or log outputs.
* **Why it was done**:
  * Prevents malformed input from causing server exceptions or SQL injection vectors.
  * Ensures zero chance of sensitive Discord bot tokens or email passwords leaking into public API endpoints or deployment logs.

---

### 4. Smart Per-Shipment Notification Routing (`notify_target`)
* **Files Modified**: [`ekart_tracker/bot.py`](file:///d:/Shipment%20Tracker/ekart_tracker/bot.py), [`ekart_tracker/storage.py`](file:///d:/Shipment%20Tracker/ekart_tracker/storage.py), [`ekart_tracker/notifier.py`](file:///d:/Shipment%20Tracker/ekart_tracker/notifier.py), [`ekart_tracker/server.py`](file:///d:/Shipment%20Tracker/ekart_tracker/server.py)
* **What was done**:
  * Added a `notify_target` attribute to each tracked package in the database.
  * When a package is added via Discord DM or server channel, the exact channel/DM ID is saved with that shipment.
  * When the background poller detects a status change, it routes the automated notification specifically to that originating thread.
* **Why it was done**:
  * Previously, automated alerts relied only on global `.env` settings (`DISCORD_CHANNEL_ID` or `DISCORD_USER_ID`).
  * Per-shipment routing allows multiple users to track packages in their own private DMs or different server channels, and each user receives automated status updates in their respective chat!

---

### 5. Discord Bot User Experience & Direct Web Links
* **File Modified**: [`ekart_tracker/bot.py`](file:///d:/Shipment%20Tracker/ekart_tracker/bot.py)
* **What was done**:
  * Created `ShipmentView` with a direct `discord.ui.Button` linking to official Ekart tracking: `https://ekartlogistics.com/shipmenttrack/{tracking_id}`.
  * Added `/stats` and `!stats` commands displaying real-time metrics (active shipments, completed deliveries, alerts sent).
  * Added unified progress calculation (`progress_percentage`) directly to data models (`models.py`) so all embeds display accurate milestone progress bars (`[🟩🟩🟩⬜⬜] 60%`).
* **Why it was done**:
  * Users can cross-verify live courier updates with a single tap on mobile or desktop without manually copying tracking IDs.
  * Provides complete visibility into the bot's background monitoring activity.

---

### 6. Timezone Standardization & Deprecation Removal
* **Files Modified**: [`ekart_tracker/bot.py`](file:///d:/Shipment%20Tracker/ekart_tracker/bot.py), [`ekart_tracker/notifier.py`](file:///d:/Shipment%20Tracker/ekart_tracker/notifier.py)
* **What was done**:
  * Replaced all instances of `datetime.utcnow()` with timezone-aware `datetime.now(timezone.utc)`.
* **Why it was done**:
  * In Python 3.12 and 3.13, `datetime.utcnow()` was officially deprecated.
  * Using timezone-aware datetimes ensures unambiguous timestamps across servers deployed in different global regions (e.g. Render Singapore, US East, or local Windows machines).

---

### 7. Containerization & Production CI/CD
* **Files Created**: [`Dockerfile`](file:///d:/Shipment%20Tracker/Dockerfile), [`docker-compose.yml`](file:///d:/Shipment%20Tracker/docker-compose.yml), [`.dockerignore`](file:///d:/Shipment%20Tracker/.dockerignore), [`.github/workflows/ci.yml`](file:///d:/Shipment%20Tracker/.github/workflows/ci.yml)
* **What was done**:
  * Multi-stage slim Docker image running as a non-privileged user (`appuser`).
  * Built-in Docker `HEALTHCHECK` pinging `/health`.
  * Persistent volume mapping for database storage (`ekart_data:/app/data`).
  * GitHub Actions automated CI matrix running unit tests across Python 3.10, 3.11, and 3.12.
* **Why it was done**:
  * Enables seamless, 1-command deployment to any cloud provider, VPS, or Kubernetes cluster.
  * Protects code quality by automatically validating every future commit against the complete test suite.

---

## 🧪 Verification & Test Coverage

The automated test suite in [`tests/`](file:///d:/Shipment%20Tracker/tests) has been expanded from 17 to **21 comprehensive unit tests**:

* `test_tracker.py`:
  * Tests CSRF token parsing from live HTML meta tags.
  * Tests response serialization into `ShipmentDetails` and `Milestone`.
  * Tests input sanitization (`sanitize_tracking_id`).
  * Tests progress percentage and terminal state calculations.
  * Tests official web portal link generation.
* `test_storage.py`:
  * Tests SQLite CRUD operations.
  * Tests `notify_target` persistence.
  * Tests `get_stats()` metrics aggregator.
  * Tests notification logging and queries.
* `test_notifier.py`:
  * Tests HTML email template rendering.
  * Tests plain text rendering.
  * Tests dry-run notification dispatching.
  * Tests dual-channel orchestration.
* `test_server.py`:
  * Tests `/health` and `/` endpoints.
  * Tests masked configuration output on `/api/status`.
  * Tests shipment creation and validation.
  * Tests simulation advancement.

All 21 tests pass in under 2 seconds:
```bash
python -m unittest discover -s tests
# Result: Ran 21 tests in 1.758s -> OK
```
