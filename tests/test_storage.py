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
        s = self.storage.add_shipment("FMPC12345", label="Test Order", is_simulated=True, notify_target="channel:123456789")
        self.assertEqual(s.tracking_id, "FMPC12345")
        self.assertEqual(s.label, "Test Order")
        self.assertTrue(s.is_simulated)
        self.assertEqual(s.notify_target, "channel:123456789")

        fetched = self.storage.get_shipment("FMPC12345")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.tracking_id, "FMPC12345")
        self.assertEqual(fetched.notify_target, "channel:123456789")

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

    def test_get_stats(self):
        self.storage.add_shipment("STAT1", is_simulated=True)
        stats = self.storage.get_stats()
        self.assertGreaterEqual(stats["total_shipments"], 1)
        self.assertIn("active_shipments", stats)
        self.assertIn("total_notifications", stats)

    def test_per_user_isolation(self):
        self.storage.add_shipment("PKG_USER_A", label="User A Shoes", user_id="user_A_999")
        self.storage.add_shipment("PKG_USER_B", label="User B Watch", user_id="user_B_888")

        # Test private list for User A
        list_a = self.storage.list_shipments(user_id="user_A_999")
        self.assertEqual(len(list_a), 1)
        self.assertEqual(list_a[0].tracking_id, "PKG_USER_A")

        # Test private list for User B
        list_b = self.storage.list_shipments(user_id="user_B_888")
        self.assertEqual(len(list_b), 1)
        self.assertEqual(list_b[0].tracking_id, "PKG_USER_B")

        # Test User B cannot delete User A's package
        can_delete = self.storage.remove_shipment("PKG_USER_A", user_id="user_B_888")
        self.assertFalse(can_delete)
        self.assertIsNotNone(self.storage.get_shipment("PKG_USER_A"))

        # Test User A can delete their own package
        can_delete_own = self.storage.remove_shipment("PKG_USER_A", user_id="user_A_999")
        self.assertTrue(can_delete_own)
        self.assertIsNone(self.storage.get_shipment("PKG_USER_A"))

if __name__ == "__main__":
    unittest.main()

