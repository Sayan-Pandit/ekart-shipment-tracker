import unittest
import re
from unittest.mock import patch, MagicMock
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

if __name__ == "__main__":
    unittest.main()

