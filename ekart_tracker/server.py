import os
import sys
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from .config import config, now_ist, format_datetime_ist
from .storage import TrackerStorage
from .models import ShipmentDetails, ShipmentStatus, sanitize_tracking_id
from .tracker import ShipmentTracker, EkartTrackingError
from .notifier import DualNotificationManager

# Configure logging
log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    log_handlers.append(logging.FileHandler(config.data_dir / "server.log", encoding="utf-8"))
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=log_handlers
)
logger = logging.getLogger("ekart_server")

class TrackingServerDaemon:
    """Background tracking daemon and REST API server."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None):
        self.host = host or config.host
        self.port = port or config.port
        self.storage = TrackerStorage()
        self.tracker = ShipmentTracker()
        self.notifier = DualNotificationManager(storage=self.storage)
        
        self.app = Flask("ekart_tracker_server")
        origins = [o.strip() for o in config.cors_origins.split(",") if o.strip()]
        CORS(self.app, origins=origins if origins else "*")
        
        self.start_time = now_ist()
        self.is_running = False
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register REST API endpoints."""

        def verify_api_key():
            """Check API key on mutating endpoints if API_KEY is set in environment."""
            if not config.api_key:
                return None
            req_key = request.headers.get("X-API-Key")
            if not req_key:
                auth = request.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    req_key = auth[7:].strip()
            if req_key != config.api_key:
                return jsonify({"error": "Unauthorized: invalid or missing API key"}), 401
            return None

        @self.app.route("/favicon.ico", methods=["GET", "HEAD"])
        def favicon():
            return Response(status=204)

        @self.app.route("/", methods=["GET", "HEAD"])
        def api_root():
            uptime_seconds = int((now_ist() - self.start_time).total_seconds())
            shipments_count = len(self.storage.list_shipments(active_only=True))
            server_time_ist = format_datetime_ist(now_ist())
            
            accept = request.headers.get("Accept", "")
            if "text/html" in accept and "application/json" not in accept:
                html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ekart Logistics Tracker & Discord Bot</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px 20px; display: flex; justify-content: center; }}
    .container {{ max-width: 680px; width: 100%; background: #1e293b; border-radius: 16px; padding: 32px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); border: 1px solid #334155; }}
    .badge {{ display: inline-flex; align-items: center; gap: 6px; background: #064e3b; color: #34d399; padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600; }}
    .dot {{ width: 8px; height: 8px; background: #10b981; border-radius: 50%; display: inline-block; animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
    h1 {{ margin: 16px 0 6px; font-size: 24px; color: #ffffff; }}
    p.sub {{ margin: 0 0 24px; color: #94a3b8; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 24px 0; }}
    .card {{ background: #0f172a; border-radius: 10px; padding: 16px; border: 1px solid #334155; }}
    .card-label {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px; }}
    .card-val {{ font-size: 20px; font-weight: 700; color: #38bdf8; margin-top: 6px; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 24px; }}
    .btn {{ background: #3b82f6; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: 500; transition: background 0.2s; }}
    .btn:hover {{ background: #2563eb; }}
    .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #334155; font-size: 12px; color: #64748b; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge"><span class="dot"></span> SYSTEM ONLINE</div>
    <h1>Ekart Shipment Tracker & Discord Bot</h1>
    <p class="sub">Production Logistics Tracking Daemon & Notification Service</p>

    <div class="grid">
      <div class="card">
        <div class="card-label">Server Timezone</div>
        <div class="card-val" style="font-size: 16px; color: #f59e0b;">IST (Asia/Kolkata)</div>
      </div>
      <div class="card">
        <div class="card-label">Current IST Time</div>
        <div class="card-val" style="font-size: 14px; color: #34d399;">{server_time_ist}</div>
      </div>
      <div class="card">
        <div class="card-label">Active Shipments</div>
        <div class="card-val">{shipments_count}</div>
      </div>
      <div class="card">
        <div class="card-label">Discord Bot</div>
        <div class="card-val" style="font-size: 16px; color: {'#10b981' if config.discord_bot_token else '#ef4444'};">{'Active' if config.discord_bot_token else 'Token Not Set'}</div>
      </div>
    </div>

    <div class="links">
      <a class="btn" href="/health">Health Check</a>
      <a class="btn" href="/api/status">System Status (JSON)</a>
      <a class="btn" href="/api/shipments">Active Shipments</a>
      <a class="btn" href="/api/stats">Database Stats</a>
    </div>

    <div class="footer">
      Running on Render Cloud &bull; Timezone: IST (UTC+05:30) &bull; Uptime: {uptime_seconds}s
      <div style="margin-top: 10px;">
        <a href="/terms" style="color: #38bdf8; text-decoration: none; margin-right: 16px;">📜 Terms of Service</a>
        <a href="/privacy" style="color: #38bdf8; text-decoration: none;">🔒 Privacy Policy</a>
      </div>
    </div>
  </div>
</body>
</html>"""
                return Response(html, mimetype="text/html")

            return jsonify({
                "service": "Ekart Logistics Shipment Tracker & Discord Bot",
                "status": "online",
                "version": "1.0.0",
                "timezone": config.timezone_name,
                "current_time_ist": server_time_ist,
                "uptime_seconds": uptime_seconds,
                "active_shipments": shipments_count,
                "endpoints": {
                    "health": "/health",
                    "status": "/api/status",
                    "shipments": "/api/shipments",
                    "notifications": "/api/notifications",
                    "stats": "/api/stats"
                },
                "discord_bot": {
                    "enabled": config.discord_bot_enabled,
                    "connected": bool(config.discord_bot_token)
                }
            })

        @self.app.route("/terms", methods=["GET"])
        def api_terms():
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Terms of Service - Ekart Shipment Tracker</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px 20px; display: flex; justify-content: center; line-height: 1.6; }
    .container { max-width: 720px; width: 100%; background: #1e293b; border-radius: 16px; padding: 36px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); border: 1px solid #334155; }
    h1 { color: #38bdf8; font-size: 26px; margin-top: 0; }
    h2 { color: #f1f5f9; font-size: 18px; margin-top: 24px; border-bottom: 1px solid #334155; padding-bottom: 6px; }
    p, li { color: #cbd5e1; font-size: 14px; }
    a { color: #38bdf8; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge { display: inline-block; background: #1e3a8a; color: #93c5fd; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; margin-bottom: 12px; }
    .footer { margin-top: 36px; padding-top: 16px; border-top: 1px solid #334155; font-size: 12px; color: #64748b; text-align: center; }
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">LEGAL DOCUMENT</div>
    <h1>Terms of Service</h1>
    <p><em>Last updated: October 30, 2026</em></p>

    <h2>1. Acceptance of Terms</h2>
    <p>By using the Ekart Shipment Tracker bot, Discord integration, REST API, or web services (collectively, the "Service"), you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use the Service.</p>

    <h2>2. Description of Service</h2>
    <p>The Service provides package monitoring, milestone tracking, and status notification alerts for shipments handled by Ekart Logistics. The Service queries publicly accessible tracking endpoints to deliver consolidated notifications via Discord and Email.</p>

    <h2>3. Disclaimer of Affiliation</h2>
    <p>Ekart Shipment Tracker is an independent utility created for personal and developer convenience. The Service is <strong>not affiliated with, authorized, maintained, sponsored, or endorsed</strong> by Flipkart Internet Pvt. Ltd., Ekart Logistics, or any of their affiliates.</p>

    <h2>4. Permitted Use & Rate Limiting</h2>
    <ul>
      <li>You agree to use the Service solely for legitimate package tracking purposes.</li>
      <li>You shall not attempt to reverse engineer, abuse, or flood the Service or carrier endpoints with excessive requests.</li>
      <li>Rate limits are enforced to protect carrier infrastructure and maintain reliability for all users.</li>
    </ul>

    <h2>5. "As Is" Warranty Disclaimer</h2>
    <p>The Service and tracking information are provided on an <strong>"AS IS" and "AS AVAILABLE"</strong> basis without warranties of any kind. We do not guarantee uninterrupted availability, timeliness, or 100% accuracy of courier tracking statuses.</p>

    <div class="footer">
      <a href="/">← Return to Dashboard</a> &bull; <a href="/privacy">Privacy Policy</a>
    </div>
  </div>
</body>
</html>"""
            return Response(html, mimetype="text/html")

        @self.app.route("/privacy", methods=["GET"])
        def api_privacy():
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Privacy Policy - Ekart Shipment Tracker</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 40px 20px; display: flex; justify-content: center; line-height: 1.6; }
    .container { max-width: 720px; width: 100%; background: #1e293b; border-radius: 16px; padding: 36px; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5); border: 1px solid #334155; }
    h1 { color: #34d399; font-size: 26px; margin-top: 0; }
    h2 { color: #f1f5f9; font-size: 18px; margin-top: 24px; border-bottom: 1px solid #334155; padding-bottom: 6px; }
    p, li { color: #cbd5e1; font-size: 14px; }
    a { color: #38bdf8; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .badge { display: inline-block; background: #064e3b; color: #6ee7b7; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; margin-bottom: 12px; }
    .footer { margin-top: 36px; padding-top: 16px; border-top: 1px solid #334155; font-size: 12px; color: #64748b; text-align: center; }
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">DATA & PRIVACY</div>
    <h1>Privacy Policy</h1>
    <p><em>Last updated: October 30, 2026</em></p>

    <h2>1. Information We Collect</h2>
    <p>Ekart Shipment Tracker collects the minimum data required to deliver package tracking services:</p>
    <ul>
      <li><strong>Tracking IDs:</strong> The shipment tracking number (e.g. <code>FMPP...</code>) you submit for tracking.</li>
      <li><strong>Discord Channel or User ID:</strong> To direct status change notifications back to the conversation or channel where you initiated tracking.</li>
      <li><strong>User-Provided Labels:</strong> Optional nicknames assigned to packages (e.g. "Gift for Mom").</li>
      <li><strong>Courier Milestones:</strong> Public transit events reported by the carrier (dates, locations, status).</li>
    </ul>

    <h2>2. Information We DO NOT Collect</h2>
    <ul>
      <li>We do <strong>not</strong> collect personal addresses, phone numbers, or recipient names.</li>
      <li>We do <strong>not</strong> collect payment information, credit cards, or purchase amounts.</li>
      <li>We do <strong>not</strong> access your Discord message history outside of bot commands.</li>
    </ul>

    <h2>3. Data Retention & Deletion</h2>
    <p>Tracking records are retained only while a shipment remains active. Users can permanently delete any tracking record and its associated history immediately by running the <code>/remove &lt;id&gt;</code> command.</p>

    <h2>4. Third-Party Sharing</h2>
    <p>We do not sell, rent, monetize, or distribute any user information to advertisers or external third parties. Tracking requests communicate directly with Ekart's publicly accessible inquiry endpoints.</p>

    <div class="footer">
      <a href="/">← Return to Dashboard</a> &bull; <a href="/terms">Terms of Service</a>
    </div>
  </div>
</body>
</html>"""
            return Response(html, mimetype="text/html")

        @self.app.route("/health", methods=["GET"])
        @self.app.route("/api/status", methods=["GET"])
        def api_status():
            uptime_seconds = (now_ist() - self.start_time).total_seconds()
            shipments = self.storage.list_shipments(active_only=True)
            notifications = self.storage.list_notifications(limit=5)
            return jsonify({
                "status": "online",
                "timezone": config.timezone_name,
                "current_time_ist": format_datetime_ist(now_ist()),
                "uptime_seconds": int(uptime_seconds),
                "started_at": self.start_time.isoformat(),
                "active_shipments_count": len(shipments),
                "poll_interval_seconds": config.poll_interval,
                "notifications": {
                    "email_enabled": config.email_enabled,
                    "email_configured": self.notifier.email_notifier.is_configured(),
                    "webhook_enabled": config.webhook_enabled,
                    "webhook_configured": self.notifier.webhook_notifier.is_configured(),
                },
                "configuration": config.to_safe_dict(),
                "recent_notifications": [n.to_dict() for n in notifications]
            })

        @self.app.route("/api/stats", methods=["GET"])
        def api_stats():
            return jsonify(self.storage.get_stats())

        @self.app.route("/api/shipments", methods=["GET"])
        def api_list_shipments():
            active_only = request.args.get("active_only", "true").lower() == "true"
            shipments = self.storage.list_shipments(active_only=active_only)
            return jsonify([s.to_dict() for s in shipments])

        @self.app.route("/api/shipments", methods=["POST"])
        def api_add_shipment():
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            data = request.get_json(force=True, silent=True) or {}
            raw_id = data.get("tracking_id", "")
            try:
                tracking_id = sanitize_tracking_id(raw_id)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            label = data.get("label", f"Package {tracking_id}")
            is_simulated = bool(data.get("is_simulated", False) or tracking_id.startswith("SIM-") or tracking_id.startswith("DEMO-"))
            notify_target = data.get("notify_target")

            # Add to database
            shipment = self.storage.add_shipment(tracking_id, label, is_simulated=is_simulated, notify_target=notify_target)

            # Perform an initial check in background or synchronously
            try:
                details = self.tracker.track(tracking_id, force_simulated=is_simulated)
                self.storage.update_shipment_details(details)
                shipment = self.storage.get_shipment(tracking_id)
            except Exception as e:
                logger.warning("Initial track on add for %s returned error: %s", tracking_id, e)

            return jsonify(shipment.to_dict() if shipment else {}), 201

        @self.app.route("/api/shipments/<tracking_id>", methods=["GET"])
        def api_get_shipment(tracking_id: str):
            clean_id = tracking_id.strip().upper()
            shipment = self.storage.get_shipment(clean_id)
            if not shipment:
                return jsonify({"error": f"Shipment {clean_id} not found"}), 404
            return jsonify(shipment.to_dict())

        @self.app.route("/api/shipments/<tracking_id>", methods=["DELETE"])
        def api_remove_shipment(tracking_id: str):
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            clean_id = tracking_id.strip().upper()
            success = self.storage.remove_shipment(clean_id)
            if not success:
                return jsonify({"error": f"Shipment {clean_id} not found"}), 404
            return jsonify({"success": True, "message": f"Shipment {clean_id} removed"})

        @self.app.route("/api/shipments/<tracking_id>/refresh", methods=["POST"])
        def api_refresh_shipment(tracking_id: str):
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            clean_id = tracking_id.strip().upper()
            shipment = self.storage.get_shipment(clean_id)
            if not shipment:
                return jsonify({"error": f"Shipment {clean_id} not found"}), 404

            try:
                details = self.tracker.track(clean_id, force_simulated=shipment.is_simulated)
                old_status = shipment.current_status
                self.storage.update_shipment_details(details)

                # Check if status changed
                notify_results = {}
                if details.status != old_status and details.status != ShipmentStatus.UNKNOWN:
                    logger.info("Status changed for %s from '%s' to '%s'", clean_id, old_status, details.status)
                    notify_results = self.notifier.notify_status_change(details, old_status)

                updated = self.storage.get_shipment(clean_id)
                return jsonify({
                    "shipment": updated.to_dict() if updated else {},
                    "status_changed": details.status != old_status,
                    "notification_dispatched": bool(notify_results),
                    "notifications": notify_results
                })
            except Exception as e:
                logger.error("Error refreshing shipment %s: %s", clean_id, e)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/shipments/<tracking_id>/simulate", methods=["POST"])
        def api_simulate_advance(tracking_id: str):
            """Step a simulated shipment to its next delivery stage."""
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            clean_id = tracking_id.strip().upper()
            shipment = self.storage.get_shipment(clean_id)
            if not shipment:
                return jsonify({"error": f"Shipment {clean_id} not found"}), 404

            old_status = shipment.current_status
            self.tracker.mock_client.set_stage_from_status(clean_id, old_status)
            new_stage = self.tracker.mock_client.advance_stage(clean_id)
            details = self.tracker.mock_client.track(clean_id)
            self.storage.update_shipment_details(details)

            notify_results = {}
            if details.status != old_status:
                logger.info("Simulated stage advanced for %s: '%s' -> '%s'", clean_id, old_status, details.status)
                notify_results = self.notifier.notify_status_change(details, old_status)

            updated = self.storage.get_shipment(clean_id)
            return jsonify({
                "shipment": updated.to_dict() if updated else {},
                "stage": new_stage,
                "status_changed": details.status != old_status,
                "notifications": notify_results
            })

        @self.app.route("/api/notifications", methods=["GET"])
        def api_get_notifications():
            tracking_id = request.args.get("tracking_id")
            try:
                limit = max(1, min(100, int(request.args.get("limit", "50"))))
            except (ValueError, TypeError):
                limit = 50
            records = self.storage.list_notifications(tracking_id=tracking_id, limit=limit)
            return jsonify([r.to_dict() for r in records])

        @self.app.route("/api/notifications/test", methods=["POST"])
        def api_test_notifications():
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            data = request.get_json(force=True, silent=True) or {}
            tracking_id = data.get("tracking_id", "TEST_FMPC01234567")
            results = self.notifier.send_test_notifications(tracking_id=tracking_id)
            return jsonify({
                "message": "Test notifications triggered for both channels (Email & Webhook)",
                "results": {k: {"success": v[0], "message": v[1]} for k, v in results.items()}
            })

        @self.app.route("/api/config", methods=["POST"])
        def api_update_config():
            auth_err = verify_api_key()
            if auth_err:
                return auth_err
            data = request.get_json(force=True, silent=True) or {}
            if "poll_interval" in data:
                config.poll_interval = max(10, int(data["poll_interval"]))
            return jsonify({
                "poll_interval_seconds": config.poll_interval,
                "email_enabled": config.email_enabled,
                "webhook_enabled": config.webhook_enabled
            })

    def _poll_worker(self) -> None:
        """Background thread that periodically checks all active shipments."""
        logger.info("Background tracking worker started. Polling interval: %d seconds.", config.poll_interval)
        while not self._stop_event.is_set():
            try:
                active_shipments = self.storage.list_shipments(active_only=True)
                for shipment in active_shipments:
                    if self._stop_event.is_set():
                        break
                    
                    tracking_id = shipment.tracking_id
                    try:
                        logger.debug("Checking package %s...", tracking_id)
                        details = self.tracker.track(tracking_id, force_simulated=shipment.is_simulated)
                        old_status = shipment.current_status

                        # Update storage
                        self.storage.update_shipment_details(details)

                        # Status change detection
                        if details.status != old_status and details.status != ShipmentStatus.UNKNOWN:
                            logger.info("[Ekart Alert] STATUS CHANGE DETECTED for %s: '%s' -> '%s'", tracking_id, old_status, details.status)
                            # Dispatch to both Email and Webhook (specifically targeting the requesting Discord channel/DM)
                            self.notifier.notify_status_change(details, old_status, notify_target=shipment.notify_target)

                    except Exception as e:
                        logger.warning("Error during periodic check for %s: %s", tracking_id, e)

                    # Short pause between individual requests to prevent burst
                    time.sleep(1)

            except Exception as e:
                logger.error("Error in background polling cycle: %s", e)

            # Wait for next cycle or stop signal
            self._stop_event.wait(timeout=config.poll_interval)

        logger.info("Background tracking worker exited cleanly.")

    def start(self) -> None:
        """Start the background poll worker and Flask server."""
        self.is_running = True
        self._write_pid()

        # Start poll thread
        self._poll_thread = threading.Thread(target=self._poll_worker, daemon=True, name="EkartPoller")
        self._poll_thread.start()

        logger.info("Starting Ekart Tracker Server daemon on http://%s:%d", self.host, self.port)
        try:
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False, threaded=True)
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully stop background worker and clean up PID file."""
        if not self.is_running:
            return
        logger.info("Stopping Ekart Tracker Server...")
        self.is_running = False
        self._stop_event.set()
        self._remove_pid()

    def _write_pid(self) -> None:
        try:
            with open(config.pid_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.warning("Could not write PID file: %s", e)

    def _remove_pid(self) -> None:
        try:
            if config.pid_file.exists():
                config.pid_file.unlink()
        except Exception as e:
            logger.warning("Could not delete PID file: %s", e)


def run_server():
    server = TrackingServerDaemon()
    server.start()

if __name__ == "__main__":
    run_server()
