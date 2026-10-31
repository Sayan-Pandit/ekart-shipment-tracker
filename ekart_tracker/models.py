import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

class ShipmentStatus:
    ORDER_CREATED = "Order Created"
    PICKED_UP = "Picked Up"
    IN_TRANSIT = "In Transit"
    REACHED_HUB = "Reached Nearest Hub"
    OUT_FOR_DELIVERY = "Out for Delivery"
    DELIVERED = "Delivered"
    FAILED_ATTEMPT = "Delivery Attempted / Failed"
    RETURNED = "Returned / Cancelled"
    UNKNOWN = "Status Pending / Not Found"

    @classmethod
    def normalize(cls, raw_status: str) -> str:
        if not raw_status:
            return cls.UNKNOWN
        s = raw_status.strip().lower()
        if "out for delivery" in s or "ofd" in s:
            return cls.OUT_FOR_DELIVERY
        elif "undelivered" in s or "failed" in s or "attempted" in s or "rescheduled" in s:
            return cls.FAILED_ATTEMPT
        elif "delivered" in s:
            return cls.DELIVERED
        elif (
            "nearest hub" in s
            or "motherhub" in s
            or "hub" in s
            or "facility" in s
            or "center" in s
            or "warehouse" in s
            or "dc" in s
            or "fmc" in s
            or "reached" in s
            or "arrived" in s
            or "received at" in s
        ):
            # Check if moving between hubs vs arrived/received
            if "dispatched" in s or "in transit" in s or "departed" in s or "loaded" in s or "bagged" in s or "shipped" in s or "forwarded" in s or "connected" in s:
                return cls.IN_TRANSIT
            elif "pickup" in s or "picked" in s:
                return cls.PICKED_UP
            return cls.REACHED_HUB
        elif "in transit" in s or "dispatched" in s or "bagged" in s or "shipped" in s or "forwarded" in s or "connected" in s:
            return cls.IN_TRANSIT
        elif "pickup" in s or "picked up" in s or "collected" in s:
            return cls.PICKED_UP
        elif "order created" in s or "manifest" in s or "created" in s:
            return cls.ORDER_CREATED
        elif "return" in s or "cancelled" in s:
            return cls.RETURNED
        return raw_status

    @classmethod
    def get_progress_percentage(cls, status: str) -> int:
        norm = cls.normalize(status)
        mapping = {
            cls.ORDER_CREATED: 15,
            cls.PICKED_UP: 30,
            cls.IN_TRANSIT: 50,
            cls.REACHED_HUB: 70,
            cls.OUT_FOR_DELIVERY: 85,
            cls.DELIVERED: 100,
            cls.FAILED_ATTEMPT: 85,
            cls.RETURNED: 100,
            cls.UNKNOWN: 5,
        }
        if norm in mapping:
            return mapping[norm]

        s = status.strip().lower()
        if "out for delivery" in s:
            return 85
        elif "motherhub" in s or "hub" in s or "facility" in s or "center" in s or "reached" in s or "arrived" in s:
            return 70
        elif "transit" in s or "dispatched" in s or "shipped" in s:
            return 50
        elif "pickup" in s or "picked" in s:
            return 30
        elif "create" in s or "manifest" in s:
            return 15
        return 10

    @classmethod
    def is_terminal_status(cls, status: str) -> bool:
        norm = cls.normalize(status)
        return norm in (cls.DELIVERED, cls.RETURNED)

# Canonical status colors for Discord embeds, email badges, and terminal styling
STATUS_HEX_COLORS = {
    ShipmentStatus.DELIVERED: "#10B981",       # Green
    ShipmentStatus.OUT_FOR_DELIVERY: "#F59E0B", # Amber / Gold
    ShipmentStatus.REACHED_HUB: "#6366F1",      # Indigo
    ShipmentStatus.IN_TRANSIT: "#3B82F6",       # Blue
    ShipmentStatus.PICKED_UP: "#8B5CF6",        # Purple
    ShipmentStatus.ORDER_CREATED: "#0EA5E9",    # Cyan
    ShipmentStatus.FAILED_ATTEMPT: "#EF4444",   # Red
    ShipmentStatus.RETURNED: "#6B7280",         # Gray
}

STATUS_INT_COLORS = {
    ShipmentStatus.DELIVERED: 0x10B981,
    ShipmentStatus.OUT_FOR_DELIVERY: 0xF59E0B,
    ShipmentStatus.REACHED_HUB: 0x6366F1,
    ShipmentStatus.IN_TRANSIT: 0x3B82F6,
    ShipmentStatus.PICKED_UP: 0x8B5CF6,
    ShipmentStatus.ORDER_CREATED: 0x0EA5E9,
    ShipmentStatus.FAILED_ATTEMPT: 0xEF4444,
    ShipmentStatus.RETURNED: 0x6B7280,
}

def sanitize_tracking_id(tracking_id: str) -> str:
    """Sanitize and validate an Ekart tracking ID (e.g. FMPC0279658213, OD1234, SIM-101)."""
    if not tracking_id or not isinstance(tracking_id, str):
        raise ValueError("Tracking ID cannot be empty.")
    clean = tracking_id.strip().upper()
    # Remove any dangerous characters, only alphanumeric, hyphen, underscore allowed
    clean = re.sub(r'[^A-Z0-9\-_]', '', clean)
    if len(clean) < 3 or len(clean) > 40:
        raise ValueError(f"Invalid tracking ID length ({len(clean)} chars). Must be between 3 and 40 characters.")
    return clean

@dataclass
class Milestone:
    date_str: str
    time_str: str
    city: str
    status_details: str
    timestamp: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Milestone":
        return cls(
            date_str=data.get("date_str", ""),
            time_str=data.get("time_str", ""),
            city=data.get("city", "N/A"),
            status_details=data.get("status_details", "Updated"),
            timestamp=data.get("timestamp")
        )

@dataclass
class ShipmentDetails:
    tracking_id: str
    status: str
    expected_delivery_date: Optional[str] = None
    expected_delivery_epoch: Optional[int] = None
    is_delivered: bool = False
    fa_shipment: bool = False
    reached_nearest_hub: bool = False
    milestones: List[Milestone] = field(default_factory=list)
    raw_data: Optional[Dict[str, Any]] = None

    @property
    def progress_percentage(self) -> int:
        if self.is_delivered:
            return 100

        current_norm = ShipmentStatus.normalize(self.status)
        if current_norm in (ShipmentStatus.FAILED_ATTEMPT, ShipmentStatus.RETURNED):
            return ShipmentStatus.get_progress_percentage(current_norm)

        base_pct = ShipmentStatus.get_progress_percentage(current_norm)

        # If Ekart flagged reached_nearest_hub, progress is at least 70%
        if self.reached_nearest_hub:
            base_pct = max(base_pct, 70)

        # Monotonicity: progress must never decrease from what previous milestones achieved!
        if self.milestones:
            for m in self.milestones:
                m_norm = ShipmentStatus.normalize(m.status_details)
                if m_norm not in (ShipmentStatus.FAILED_ATTEMPT, ShipmentStatus.RETURNED):
                    m_pct = ShipmentStatus.get_progress_percentage(m_norm)
                    if m_pct > base_pct and m_pct < 100:
                        base_pct = m_pct

        return base_pct

    @property
    def is_terminal(self) -> bool:
        return self.is_delivered or ShipmentStatus.is_terminal_status(self.status)

    @property
    def current_location(self) -> str:
        """Return the most recent hub/city location or transit state."""
        if self.milestones:
            latest = self.milestones[-1]
            city = (latest.city or "").strip()
            if city and city not in ("N/A", "Facility / Transit Hub"):
                return city
            return latest.status_details
        return "Logistics Hub"

    @property
    def deduplicated_milestones(self) -> List[Milestone]:
        """Remove consecutive duplicate scans at the same hub and status."""
        if not self.milestones:
            return []
        cleaned: List[Milestone] = [self.milestones[0]]
        for m in self.milestones[1:]:
            prev = cleaned[-1]
            same_city = (m.city or "").strip().lower() == (prev.city or "").strip().lower()
            same_status = (m.status_details or "").strip().lower() == (prev.status_details or "").strip().lower()
            if same_city and same_status:
                continue
            cleaned.append(m)
        return cleaned

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracking_id": self.tracking_id,
            "status": self.status,
            "progress_percentage": self.progress_percentage,
            "expected_delivery_date": self.expected_delivery_date,
            "expected_delivery_epoch": self.expected_delivery_epoch,
            "is_delivered": self.is_delivered,
            "is_terminal": self.is_terminal,
            "fa_shipment": self.fa_shipment,
            "reached_nearest_hub": self.reached_nearest_hub,
            "current_location": self.current_location,
            "milestones": [m.to_dict() for m in self.milestones],
            "raw_data": self.raw_data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShipmentDetails":
        milestones = [Milestone.from_dict(m) for m in data.get("milestones", [])]
        return cls(
            tracking_id=data.get("tracking_id", ""),
            status=data.get("status", ShipmentStatus.UNKNOWN),
            expected_delivery_date=data.get("expected_delivery_date"),
            expected_delivery_epoch=data.get("expected_delivery_epoch"),
            is_delivered=data.get("is_delivered", False),
            fa_shipment=data.get("fa_shipment", False),
            reached_nearest_hub=data.get("reached_nearest_hub", False),
            milestones=milestones,
            raw_data=data.get("raw_data")
        )

@dataclass
class TrackedShipment:
    tracking_id: str
    label: str
    is_simulated: bool
    current_status: str
    expected_delivery: Optional[str]
    is_delivered: bool
    created_at: str
    last_checked_at: Optional[str]
    is_active: bool
    milestones: List[Milestone] = field(default_factory=list)
    notify_target: Optional[str] = None
    user_id: Optional[str] = None

    @property
    def progress_percentage(self) -> int:
        return ShipmentStatus.get_progress_percentage(self.current_status)

    @property
    def is_terminal(self) -> bool:
        return self.is_delivered or ShipmentStatus.is_terminal_status(self.current_status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracking_id": self.tracking_id,
            "label": self.label,
            "is_simulated": self.is_simulated,
            "current_status": self.current_status,
            "progress_percentage": self.progress_percentage,
            "expected_delivery": self.expected_delivery,
            "is_delivered": self.is_delivered,
            "is_terminal": self.is_terminal,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "is_active": self.is_active,
            "milestones": [m.to_dict() for m in self.milestones],
            "notify_target": self.notify_target,
            "user_id": self.user_id
        }

@dataclass
class NotificationRecord:
    id: Optional[int]
    tracking_id: str
    channel: str # email, webhook
    event_type: str # status_change, milestone, test
    message: str
    status: str # sent, failed, simulated
    created_at: str
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
