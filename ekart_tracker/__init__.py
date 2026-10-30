"""
Ekart Shipment Tracker
Platform: Server
Notifications: Both (Email + Webhook)
Interface: Terminal
"""

__version__ = "1.0.0"

from .tracker import ShipmentTracker, EkartLiveClient, MockEkartClient
from .storage import TrackerStorage
from .notifier import DualNotificationManager, EmailNotifier, WebhookNotifier
from .server import TrackingServerDaemon
from .models import ShipmentDetails, Milestone, TrackedShipment, ShipmentStatus

