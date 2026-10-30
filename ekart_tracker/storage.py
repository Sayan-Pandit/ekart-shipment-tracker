import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import TrackedShipment, Milestone, NotificationRecord, ShipmentDetails
from .config import config

logger = logging.getLogger(__name__)

class TrackerStorage:
    """Thread-safe SQLite storage for tracked Ekart shipments and notification records."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables if they do not already exist."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
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
                    milestones_json TEXT
                )
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
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def add_shipment(self, tracking_id: str, label: str = "", is_simulated: bool = False) -> TrackedShipment:
        clean_id = tracking_id.strip().upper()
        now_str = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shipments (
                    tracking_id, label, is_simulated, current_status, expected_delivery,
                    is_delivered, created_at, last_checked_at, is_active, milestones_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(tracking_id) DO UPDATE SET
                    label = excluded.label,
                    is_active = 1,
                    is_simulated = excluded.is_simulated
            """, (
                clean_id,
                label or f"Ekart Package {clean_id}",
                1 if is_simulated else 0,
                "Initialized",
                None,
                0,
                now_str,
                None,
                json.dumps([])
            ))
            conn.commit()
        finally:
            conn.close()
        return self.get_shipment(clean_id) # type: ignore

    def get_shipment(self, tracking_id: str) -> Optional[TrackedShipment]:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shipments WHERE tracking_id = ?", (clean_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_shipment(row)
        finally:
            conn.close()

    def list_shipments(self, active_only: bool = True) -> List[TrackedShipment]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if active_only:
                cursor.execute("SELECT * FROM shipments WHERE is_active = 1 ORDER BY created_at DESC")
            else:
                cursor.execute("SELECT * FROM shipments ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [self._row_to_shipment(r) for r in rows]
        finally:
            conn.close()

    def update_shipment_details(self, details: ShipmentDetails) -> None:
        now_str = datetime.now().isoformat()
        milestones_json = json.dumps([m.to_dict() for m in details.milestones])
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE shipments SET
                    current_status = ?,
                    expected_delivery = ?,
                    is_delivered = ?,
                    last_checked_at = ?,
                    milestones_json = ?
                WHERE tracking_id = ?
            """, (
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

    def remove_shipment(self, tracking_id: str) -> bool:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM shipments WHERE tracking_id = ?", (clean_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def deactivate_shipment(self, tracking_id: str) -> bool:
        clean_id = tracking_id.strip().upper()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE shipments SET is_active = 0 WHERE tracking_id = ?", (clean_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def log_notification(self, record: NotificationRecord) -> int:
        now_str = record.created_at or datetime.now().isoformat()
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notifications (
                    tracking_id, channel, event_type, message, status, created_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record.tracking_id,
                record.channel,
                record.event_type,
                record.message,
                record.status,
                now_str,
                record.error_message
            ))
            conn.commit()
            return cursor.lastrowid # type: ignore
        finally:
            conn.close()

    def list_notifications(self, tracking_id: Optional[str] = None, limit: int = 50) -> List[NotificationRecord]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if tracking_id:
                cursor.execute("""
                    SELECT * FROM notifications 
                    WHERE tracking_id = ? 
                    ORDER BY id DESC LIMIT ?
                """, (tracking_id.strip().upper(), limit))
            else:
                cursor.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
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

    def _row_to_shipment(self, row: sqlite3.Row) -> TrackedShipment:
        milestones_raw = json.loads(row["milestones_json"] or "[]")
        milestones = [Milestone.from_dict(m) for m in milestones_raw]
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
            milestones=milestones
        )
