import unittest
import tempfile
from pathlib import Path
from ekart_tracker.storage import TrackerStorage
from ekart_tracker.models import ShipmentDetails, Milestone, NotificationRecord

class TestStorage(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_tracker.db"
        self.storage = TrackerStorage(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_and_get_shipment(self):
        s = self.storage.add_shipment("FMPC12345", label="Test Order", is_simulated=True)
        self.assertEqual(s.tracking_id, "FMPC12345")
        self.assertEqual(s.label, "Test Order")
        self.assertTrue(s.is_simulated)

        fetched = self.storage.get_shipment("FMPC12345")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.tracking_id, "FMPC12345")

    def test_update_shipment_details(self):
        self.storage.add_shipment("FMPC12345")
        details = ShipmentDetails(
            tracking_id="FMPC12345",
            status="In Transit",
            expected_delivery_date="2026-11-01",
            is_delivered=False,
            milestones=[
                Milestone(date_str="Oct 30", time_str="10:00 AM", city="Delhi", status_details="Shipped")
            ]
        )
        self.storage.update_shipment_details(details)

        fetched = self.storage.get_shipment("FMPC12345")
        self.assertEqual(fetched.current_status, "In Transit")
        self.assertEqual(len(fetched.milestones), 1)
        self.assertEqual(fetched.milestones[0].city, "Delhi")

    def test_remove_shipment(self):
        self.storage.add_shipment("REMOVE123")
        self.assertTrue(self.storage.remove_shipment("REMOVE123"))
        self.assertIsNone(self.storage.get_shipment("REMOVE123"))

    def test_notifications_log(self):
        rec = NotificationRecord(
            id=None,
            tracking_id="FMPC123",
            channel="email",
            event_type="status_change",
            message="Out for Delivery",
            status="sent",
            created_at="2026-10-30T10:00:00",
            error_message=None
        )
        row_id = self.storage.log_notification(rec)
        self.assertGreater(row_id, 0)

        logs = self.storage.list_notifications(tracking_id="FMPC123")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].channel, "email")
        self.assertEqual(logs[0].status, "sent")

if __name__ == "__main__":
    unittest.main()

