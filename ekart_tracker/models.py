import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
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
        if "delivered" in s:
            return cls.DELIVERED
        elif "out for delivery" in s:
            return cls.OUT_FOR_DELIVERY
        elif "nearest hub" in s or "at hub" in s or "reached facility" in s or "received at facility" in s:
            return cls.REACHED_HUB
        elif "in transit" in s or "dispatched" in s or "bagged" in s or "shipped" in s:
            return cls.IN_TRANSIT
        elif "pickup" in s or "picked up" in s:
            return cls.PICKED_UP
        elif "order created" in s or "manifest" in s:
            return cls.ORDER_CREATED
        elif "failed" in s or "undelivered" in s:
            return cls.FAILED_ATTEMPT
        elif "return" in s or "cancelled" in s:
            return cls.RETURNED
        return raw_status

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
    is_delivered: bool = False
    fa_shipment: bool = False
    reached_nearest_hub: bool = False
    milestones: List[Milestone] = field(default_factory=list)
    raw_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracking_id": self.tracking_id,
            "status": self.status,
            "expected_delivery_date": self.expected_delivery_date,
            "is_delivered": self.is_delivered,
            "fa_shipment": self.fa_shipment,
            "reached_nearest_hub": self.reached_nearest_hub,
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracking_id": self.tracking_id,
            "label": self.label,
            "is_simulated": self.is_simulated,
            "current_status": self.current_status,
            "expected_delivery": self.expected_delivery,
            "is_delivered": self.is_delivered,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "is_active": self.is_active,
            "milestones": [m.to_dict() for m in self.milestones]
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

