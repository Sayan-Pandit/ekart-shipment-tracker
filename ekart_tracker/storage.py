import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import TrackedShipment, Milestone, NotificationRecord, ShipmentDetails
from .config import config, now_ist

logger = logging.getLogger(__name__)

class TrackerStorage:
    """
    Thread-safe storage for tracked Ekart shipments and notification records.
    Automatically uses PostgreSQL if DATABASE_URL is set; otherwise falls back to SQLite.
    """

    def __init__(self, db_path: Optional[Path] = None, database_url: Optional[str] = None):
        raw_db_url = database_url or config.database_url
        if raw_db_url and raw_db_url.startswith("postgres://"):
            raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
        self.database_url = raw_db_url
        self.is_postgres = bool(self.database_url)
        self.db_path = db_path or config.db_path
        self._init_db()

    def _get_connection(self):
        if self.is_postgres:
            import psycopg2
            return psycopg2.connect(self.database_url)
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
            except Exception:
                pass
            return conn

    def _get_cursor(self, conn):
        if self.is_postgres:
            import psycopg2.extras
            return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return conn.cursor()

    def _query(self, sql: str) -> str:
        """Translate SQLite '?' placeholders to PostgreSQL '%s' when running under Postgres."""
        if self.is_postgres:
            return sql.replace("?", "%s")
        return sql

    def _init_db(self) -> None:
        """Create tables if they do not already exist."""
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            if self.is_postgres:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS shipments (
                        tracking_id VARCHAR(100) PRIMARY KEY,
                        label VARCHAR(255),
                        is_simulated INTEGER DEFAULT 0,
                        current_status VARCHAR(100),
                        expected_delivery VARCHAR(100),
                        is_delivered INTEGER DEFAULT 0,
                        created_at VARCHAR(100),
                        last_checked_at VARCHAR(100),
                        is_active INTEGER DEFAULT 1,
                        milestones_json TEXT,
                        notify_target VARCHAR(100),
                        user_id VARCHAR(100)
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id SERIAL PRIMARY KEY,
                        tracking_id VARCHAR(100),
                        channel VARCHAR(50),
                        event_type VARCHAR(50),
                        message TEXT,
                        status VARCHAR(50),
                        created_at VARCHAR(100),
                        error_message TEXT
                    );
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS shipments (
                        tracking_id TEXT PRIMARY KEY,
                        label TEXT,
                        is_simulated INTEGER DEFAULT 0,
                        current_status TEXT,
                        expected_delivery TEXT,
                        is_delivered INTEGER DEFAULT 0,
                        created_at TEXT,
                        last_checked_at TEXT,
                        is_active INTEGER DEFAULT 1,
                        milestones_json TEXT,
                        notify_target TEXT,
                        user_id TEXT
                    );
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tracking_id TEXT,
                        channel TEXT,
                        event_type TEXT,
                        message TEXT,
                        status TEXT,
                        created_at TEXT,
                        error_message TEXT
                    );
                """)

            # Safe migrations for existing databases
            for col in ("notify_target", "user_id"):
                try:
                    cursor.execute(f"ALTER TABLE shipments ADD COLUMN {col} TEXT;")
                    conn.commit()
                except Exception:
                    if self.is_postgres:
                        conn.rollback()

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shipments_active ON shipments (is_active, last_checked_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_shipments_user ON shipments (user_id, is_active);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_tid ON notifications (tracking_id, created_at);")
            conn.commit()
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Return system-wide statistics for monitoring and dashboards."""
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute("SELECT COUNT(*) FROM shipments")
            total_shipments = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM shipments WHERE is_active = 1")
            active_shipments = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM shipments WHERE is_delivered = 1")
            delivered_shipments = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM shipments WHERE is_simulated = 1")
            simulated_shipments = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM notifications")
            total_notifications = cursor.fetchone()[0]

            return {
                "total_shipments": total_shipments,
                "active_shipments": active_shipments,
                "delivered_shipments": delivered_shipments,
                "simulated_shipments": simulated_shipments,
                "total_notifications": total_notifications,
                "database_engine": "PostgreSQL" if self.is_postgres else "SQLite"
            }
        finally:
            conn.close()

    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Prune notifications older than N days."""
        from datetime import timedelta
        cutoff = (now_ist() - timedelta(days=days)).isoformat()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute(self._query("DELETE FROM notifications WHERE created_at < ?"), (cutoff,))
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def add_shipment(self, tracking_id: str, label: str = "", is_simulated: bool = False, notify_target: Optional[str] = None, user_id: Optional[str] = None) -> TrackedShipment:
        clean_id = tracking_id.strip().upper()
        now_str = now_ist().isoformat()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute(self._query("""
                INSERT INTO shipments (
                    tracking_id, label, is_simulated, current_status, expected_delivery,
                    is_delivered, created_at, last_checked_at, is_active, milestones_json, notify_target, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(tracking_id) DO UPDATE SET
                    label = excluded.label,
                    is_active = 1,
                    is_simulated = excluded.is_simulated,
                    notify_target = COALESCE(excluded.notify_target, shipments.notify_target),
                    user_id = COALESCE(excluded.user_id, shipments.user_id)
            """), (
                clean_id,
                label or f"Ekart Package {clean_id}",
                1 if is_simulated else 0,
                "Initialized",
                None,
                0,
                now_str,
                None,
                json.dumps([]),
                notify_target,
                user_id
            ))
            conn.commit()
        finally:
            conn.close()
        return self.get_shipment(clean_id) # type: ignore

    def get_shipment(self, tracking_id: str) -> Optional[TrackedShipment]:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute(self._query("SELECT * FROM shipments WHERE tracking_id = ?"), (clean_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_shipment(row)
        finally:
            conn.close()

    def list_shipments(self, user_id: Optional[str] = None, active_only: bool = True) -> List[TrackedShipment]:
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            if user_id:
                if active_only:
                    cursor.execute(self._query("SELECT * FROM shipments WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC"), (user_id,))
                else:
                    cursor.execute(self._query("SELECT * FROM shipments WHERE user_id = ? ORDER BY created_at DESC"), (user_id,))
            else:
                if active_only:
                    cursor.execute(self._query("SELECT * FROM shipments WHERE is_active = 1 ORDER BY created_at DESC"))
                else:
                    cursor.execute(self._query("SELECT * FROM shipments ORDER BY created_at DESC"))
            rows = cursor.fetchall()
            return [self._row_to_shipment(r) for r in rows]
        finally:
            conn.close()

    def update_shipment_details(self, details: ShipmentDetails) -> None:
        now_str = now_ist().isoformat()
        milestones_json = json.dumps([m.to_dict() for m in details.milestones])
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute(self._query("""
                UPDATE shipments SET
                    current_status = ?,
                    expected_delivery = ?,
                    is_delivered = ?,
                    last_checked_at = ?,
                    milestones_json = ?
                WHERE tracking_id = ?
            """), (
                details.status,
                details.expected_delivery_date,
                1 if details.is_delivered else 0,
                now_str,
                milestones_json,
                details.tracking_id
            ))
            conn.commit()
        finally:
            conn.close()

    def remove_shipment(self, tracking_id: str, user_id: Optional[str] = None) -> bool:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            if user_id:
                cursor.execute(self._query("DELETE FROM shipments WHERE tracking_id = ? AND (user_id = ? OR user_id IS NULL)"), (clean_id, user_id))
            else:
                cursor.execute(self._query("DELETE FROM shipments WHERE tracking_id = ?"), (clean_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def deactivate_shipment(self, tracking_id: str) -> bool:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            cursor.execute(self._query("UPDATE shipments SET is_active = 0 WHERE tracking_id = ?"), (clean_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def log_notification(self, record: NotificationRecord) -> int:
        now_str = record.created_at or now_ist().isoformat()
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            if self.is_postgres:
                cursor.execute(self._query("""
                    INSERT INTO notifications (
                        tracking_id, channel, event_type, message, status, created_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
                """), (
                    record.tracking_id,
                    record.channel,
                    record.event_type,
                    record.message,
                    record.status,
                    now_str,
                    record.error_message
                ))
                inserted_id = cursor.fetchone()[0]
            else:
                cursor.execute(self._query("""
                    INSERT INTO notifications (
                        tracking_id, channel, event_type, message, status, created_at, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (
                    record.tracking_id,
                    record.channel,
                    record.event_type,
                    record.message,
                    record.status,
                    now_str,
                    record.error_message
                ))
                inserted_id = cursor.lastrowid # type: ignore
            conn.commit()
            return inserted_id
        finally:
            conn.close()

    def list_notifications(self, tracking_id: Optional[str] = None, limit: int = 50) -> List[NotificationRecord]:
        conn = self._get_connection()
        try:
            cursor = self._get_cursor(conn)
            if tracking_id:
                cursor.execute(self._query("""
                    SELECT * FROM notifications 
                    WHERE tracking_id = ? 
                    ORDER BY id DESC LIMIT ?
                """), (tracking_id.strip().upper(), limit))
            else:
                cursor.execute(self._query("SELECT * FROM notifications ORDER BY id DESC LIMIT ?"), (limit,))
            rows = cursor.fetchall()
            return [
                NotificationRecord(
                    id=r["id"],
                    tracking_id=r["tracking_id"],
                    channel=r["channel"],
                    event_type=r["event_type"],
                    message=r["message"],
                    status=r["status"],
                    created_at=r["created_at"],
                    error_message=r["error_message"]
                )
                for r in rows
            ]
        finally:
            conn.close()

    def _row_to_shipment(self, row: Any) -> TrackedShipment:
        milestones_raw = json.loads(row["milestones_json"] or "[]")
        milestones = [Milestone.from_dict(m) for m in milestones_raw]
        notify_target = None
        try:
            notify_target = row["notify_target"]
        except Exception:
            pass
        user_id = None
        try:
            user_id = row["user_id"]
        except Exception:
            pass
        return TrackedShipment(
            tracking_id=row["tracking_id"],
            label=row["label"] or "",
            is_simulated=bool(row["is_simulated"]),
            current_status=row["current_status"] or "Pending",
            expected_delivery=row["expected_delivery"],
            is_delivered=bool(row["is_delivered"]),
            created_at=row["created_at"],
            last_checked_at=row["last_checked_at"],
            is_active=bool(row["is_active"]),
            milestones=milestones,
            notify_target=notify_target,
            user_id=user_id
        )
