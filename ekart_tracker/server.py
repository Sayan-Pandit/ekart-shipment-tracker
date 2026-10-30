import os
import sys
import time
import signal
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, jsonify, request
from flask_cors import CORS

from .config import config
from .storage import TrackerStorage
from .models import ShipmentDetails, ShipmentStatus
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
        CORS(self.app)
        
        self.start_time = datetime.now()
        self.is_running = False
        self._stop_event = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register REST API endpoints."""

        @self.app.route("/", methods=["GET"])
        def api_root():
            uptime_seconds = int((datetime.now() - self.start_time).total_seconds())
            shipments_count = len(self.storage.list_shipments(active_only=True))
            return jsonify({
                "service": "Ekart Logistics Shipment Tracker & Discord Bot",
                "status": "online",
                "version": "1.0.0",
                "uptime_seconds": uptime_seconds,
                "active_shipments": shipments_count,
                "endpoints": {
                    "health": "/health",
                    "status": "/api/status",
                    "shipments": "/api/shipments",
                    "notifications": "/api/notifications"
                },
                "discord_bot": {
                    "enabled": config.discord_bot_enabled,
                    "connected": bool(config.discord_bot_token)
                }
            })

        @self.app.route("/health", methods=["GET"])
        @self.app.route("/api/status", methods=["GET"])
        def api_status():
            uptime_seconds = (datetime.now() - self.start_time).total_seconds()
            shipments = self.storage.list_shipments(active_only=True)
            notifications = self.storage.list_notifications(limit=5)
            return jsonify({
                "status": "online",
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
                "recent_notifications": [n.to_dict() for n in notifications]
            })

        @self.app.route("/api/shipments", methods=["GET"])
        def api_list_shipments():
            active_only = request.args.get("active_only", "true").lower() == "true"
            shipments = self.storage.list_shipments(active_only=active_only)
            return jsonify([s.to_dict() for s in shipments])

        @self.app.route("/api/shipments", methods=["POST"])
        def api_add_shipment():
            data = request.get_json(force=True, silent=True) or {}
            tracking_id = data.get("tracking_id", "").strip().upper()
            if not tracking_id:
                return jsonify({"error": "tracking_id is required"}), 400

            label = data.get("label", f"Package {tracking_id}")
            is_simulated = bool(data.get("is_simulated", False) or tracking_id.startswith("SIM-") or tracking_id.startswith("DEMO-"))

            # Add to database
            shipment = self.storage.add_shipment(tracking_id, label, is_simulated=is_simulated)

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
            clean_id = tracking_id.strip().upper()
            success = self.storage.remove_shipment(clean_id)
            if not success:
                return jsonify({"error": f"Shipment {clean_id} not found"}), 404
            return jsonify({"success": True, "message": f"Shipment {clean_id} removed"})

        @self.app.route("/api/shipments/<tracking_id>/refresh", methods=["POST"])
        def api_refresh_shipment(tracking_id: str):
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
            limit = int(request.args.get("limit", "50"))
            records = self.storage.list_notifications(tracking_id=tracking_id, limit=limit)
            return jsonify([r.to_dict() for r in records])

        @self.app.route("/api/notifications/test", methods=["POST"])
        def api_test_notifications():
            data = request.get_json(force=True, silent=True) or {}
            tracking_id = data.get("tracking_id", "TEST_FMPC01234567")
            results = self.notifier.send_test_notifications(tracking_id=tracking_id)
            return jsonify({
                "message": "Test notifications triggered for both channels (Email & Webhook)",
                "results": {k: {"success": v[0], "message": v[1]} for k, v in results.items()}
            })

        @self.app.route("/api/config", methods=["POST"])
        def api_update_config():
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
