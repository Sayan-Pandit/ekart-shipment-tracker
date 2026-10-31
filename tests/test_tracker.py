import unittest
import re
from ekart_tracker.tracker import EkartLiveClient, MockEkartClient, ShipmentTracker
from ekart_tracker.models import ShipmentStatus

class TestEkartTracker(unittest.TestCase):

    def test_mock_client_lifecycle(self):
        client = MockEkartClient()
        details = client.track("SIM-TEST1")
        self.assertEqual(details.status, "Order Created")
        self.assertEqual(len(details.milestones), 1)

        stage = client.advance_stage("SIM-TEST1")
        self.assertEqual(stage, 1)
        details = client.track("SIM-TEST1")
        self.assertEqual(details.status, "Picked Up")
        self.assertEqual(len(details.milestones), 2)

        # Advance to delivery
        for _ in range(10):
            client.advance_stage("SIM-TEST1")
        details = client.track("SIM-TEST1")
        self.assertEqual(details.status, "Delivered")
        self.assertTrue(details.is_delivered)

    def test_parse_response_success(self):
        client = EkartLiveClient()
        mock_raw = {
            "FMPC0001": {
                "shipmentTrackingDetails": [
                    {
                        "date": 1698750000000,
                        "city": "Mumbai",
                        "statusDetails": "Order Created"
                    },
                    {
                        "date": 1698760000000,
                        "city": "Bengaluru",
                        "statusDetails": "Out for Delivery"
                    }
                ],
                "expectedDeliveryDate": 1698800000000,
                "faShipment": True,
                "reachedNearestHub": True
            }
        }
        details = client._parse_response("FMPC0001", mock_raw)
        self.assertEqual(details.tracking_id, "FMPC0001")
        self.assertEqual(details.status, ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(len(details.milestones), 2)
        self.assertEqual(details.milestones[-1].city, "Bengaluru")
        self.assertTrue(details.reached_nearest_hub)
        self.assertIsNotNone(details.expected_delivery_date)

    def test_parse_response_empty(self):
        client = EkartLiveClient()
        details = client._parse_response("FMPC0000", {})
        self.assertEqual(details.status, ShipmentStatus.UNKNOWN)
        self.assertEqual(len(details.milestones), 0)

    def test_csrf_extraction(self):
        html = '<html><head><meta name="csrf-token" content="test-token-12345" /></head></html>'
        match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "test-token-12345")

    def test_unified_tracker_routing(self):
        tracker = ShipmentTracker()
        sim_details = tracker.track("SIM-ABC", force_simulated=True)
        self.assertIn("SIM-ABC", sim_details.tracking_id)
        self.assertEqual(sim_details.status, "Order Created")

    def test_sanitize_tracking_id(self):
        from ekart_tracker.models import sanitize_tracking_id
        self.assertEqual(sanitize_tracking_id("  fmpc0123  "), "FMPC0123")
        self.assertEqual(sanitize_tracking_id("SIM-TEST_99"), "SIM-TEST_99")
        with self.assertRaises(ValueError):
            sanitize_tracking_id("")
        with self.assertRaises(ValueError):
            sanitize_tracking_id("ab") # too short

    def test_progress_percentage(self):
        from ekart_tracker.models import ShipmentDetails, ShipmentStatus
        d = ShipmentDetails(tracking_id="TEST", status=ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(d.progress_percentage, 85)
        self.assertFalse(d.is_terminal)

        d2 = ShipmentDetails(tracking_id="TEST", status=ShipmentStatus.DELIVERED, is_delivered=True)
        self.assertEqual(d2.progress_percentage, 100)
        self.assertTrue(d2.is_terminal)

    def test_get_tracking_url(self):
        url = ShipmentTracker.get_tracking_url("fmpc123")
        self.assertEqual(url, "https://ekartlogistics.com/shipmenttrack/FMPC123")

    def test_ist_timestamp_formatting(self):
        from ekart_tracker.config import from_timestamp_ist, now_ist
        # Timestamp for 2023-11-01 00:00:00 UTC = 2023-11-01 05:30:00 IST
        utc_epoch_ms = 1698796800000
        dt_ist = from_timestamp_ist(utc_epoch_ms)
        self.assertEqual(dt_ist.strftime("%H:%M"), "05:30")
        
        # Test now_ist has correct offset (+05:30)
        curr = now_ist()
        self.assertIsNotNone(curr.tzinfo)
        self.assertEqual(curr.strftime("%z"), "+0530")

        # Test Mock client produces IST timestamps
        mock = MockEkartClient()
        details = mock.track("SIM-IST-01")
        self.assertTrue(any("IST" in m.time_str for m in details.milestones))
        self.assertIsNotNone(details.expected_delivery_epoch)

    def test_deduplicated_milestones_and_location(self):
        from ekart_tracker.models import Milestone, ShipmentDetails
        m1 = Milestone(date_str="Oct 30", time_str="10:00 AM", city="Nadia", status_details="Received at Hub")
        m2 = Milestone(date_str="Oct 30", time_str="10:02 AM", city="Nadia", status_details="Received at Hub") # Duplicate
        m3 = Milestone(date_str="Oct 30", time_str="11:30 AM", city="Uluberia", status_details="Dispatched")
        
        details = ShipmentDetails(
            tracking_id="TEST-DUP",
            status="In Transit",
            milestones=[m1, m2, m3]
        )
        self.assertEqual(len(details.milestones), 3)
        self.assertEqual(len(details.deduplicated_milestones), 2)
        self.assertEqual(details.deduplicated_milestones[0].city, "Nadia")
        self.assertEqual(details.deduplicated_milestones[1].city, "Uluberia")
        self.assertEqual(details.current_location, "Uluberia")

    def test_status_normalization_ordering(self):
        # Ensure Out for Delivery does not match Delivered
        self.assertEqual(ShipmentStatus.normalize("Out for Delivery"), ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(ShipmentStatus.normalize("Package is out for delivery today"), ShipmentStatus.OUT_FOR_DELIVERY)
        self.assertEqual(ShipmentStatus.get_progress_percentage("Out for Delivery"), 85)

        # Ensure Undelivered matches FAILED_ATTEMPT and not Delivered
        self.assertEqual(ShipmentStatus.normalize("Undelivered - Customer unavailable"), ShipmentStatus.FAILED_ATTEMPT)
        self.assertEqual(ShipmentStatus.normalize("Delivery failed"), ShipmentStatus.FAILED_ATTEMPT)

        # Ensure Delivered matches correctly
        self.assertEqual(ShipmentStatus.normalize("Delivered to recipient"), ShipmentStatus.DELIVERED)
        self.assertEqual(ShipmentStatus.normalize("Shipment Delivered"), ShipmentStatus.DELIVERED)
        self.assertEqual(ShipmentStatus.get_progress_percentage("Delivered"), 100)

    def test_motherhub_and_monotonic_progress(self):
        from ekart_tracker.models import ShipmentDetails, Milestone

        # Test hub and motherhub normalization
        self.assertEqual(ShipmentStatus.normalize("Received at Motherhub_ULB"), ShipmentStatus.IN_TRANSIT)
        self.assertEqual(ShipmentStatus.get_progress_percentage("Received at Motherhub_ULB"), 60)
        self.assertEqual(ShipmentStatus.normalize("Dispatched to Motherhub_ULB"), ShipmentStatus.IN_TRANSIT)
        self.assertEqual(ShipmentStatus.get_progress_percentage("Dispatched to Motherhub_ULB"), 50)
        self.assertEqual(ShipmentStatus.normalize("Received at Delivery Center"), ShipmentStatus.REACHED_HUB)
        self.assertEqual(ShipmentStatus.get_progress_percentage("Received at Delivery Center"), 70)

        # Test monotonic progress across journey
        d = ShipmentDetails(
            tracking_id="FMPP4428292973",
            status="Received at Motherhub_ULB",
            reached_nearest_hub=False,
            milestones=[
                Milestone("Oct 30", "06:32 PM", "Nadia", "Shipment Created"),
                Milestone("Oct 30", "06:32 PM", "Nadia", "Dispatched to Motherhub_HRN"),
                Milestone("Oct 30", "08:29 PM", "Uluberia", "Dispatched to Motherhub_ULB"),
                Milestone("Oct 31", "03:27 AM", "Uluberia", "Received at Motherhub_ULB")
            ]
        )
        self.assertEqual(d.progress_percentage, 60)

        # Ensure that even if current status is temporarily unknown, progress does not regress
        d_unknown = ShipmentDetails(
            tracking_id="FMPP4428292973",
            status="Some Temporary Internal Scan",
            milestones=[
                Milestone("Oct 30", "06:32 PM", "Nadia", "Shipment Created"),
                Milestone("Oct 30", "06:32 PM", "Nadia", "Dispatched to Motherhub_HRN")
            ]
        )
        self.assertEqual(d_unknown.progress_percentage, 50)

if __name__ == "__main__":
    unittest.main()

