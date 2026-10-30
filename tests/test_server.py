import unittest
from ekart_tracker.server import TrackingServerDaemon

class TestServerAPI(unittest.TestCase):

    def setUp(self):
        self.server = TrackingServerDaemon(host="127.0.0.1", port=5099)
        self.app = self.server.app
        self.client = self.app.test_client()

    def test_health_and_status(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "online")
        self.assertIn("notifications", data)

    def test_add_and_list_shipments(self):
        resp = self.client.post("/api/shipments", json={
            "tracking_id": "TEST_PKG_001",
            "label": "Headphones",
            "is_simulated": True
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertEqual(data["tracking_id"], "TEST_PKG_001")

        # List
        resp2 = self.client.get("/api/shipments")
        self.assertEqual(resp2.status_code, 200)
        items = resp2.get_json()
        self.assertTrue(any(i["tracking_id"] == "TEST_PKG_001" for i in items))

    def test_simulate_endpoint(self):
        self.client.post("/api/shipments", json={
            "tracking_id": "SIM_SRV_01",
            "label": "Test Sim",
            "is_simulated": True
        })
        resp = self.client.post("/api/shipments/SIM_SRV_01/simulate")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("stage", data)
        self.assertIn("shipment", data)

    def test_notifications_test_endpoint(self):
        resp = self.client.post("/api/notifications/test", json={
            "tracking_id": "FMPC_SRV_TEST"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("results", data)
        self.assertIn("email", data["results"])
        self.assertIn("webhook", data["results"])

    def test_terms_and_privacy_endpoints(self):
        resp_terms = self.client.get("/terms")
        self.assertEqual(resp_terms.status_code, 200)
        self.assertIn(b"Terms of Service", resp_terms.data)

        resp_priv = self.client.get("/privacy")
        self.assertEqual(resp_priv.status_code, 200)
        self.assertIn(b"Privacy Policy", resp_priv.data)

if __name__ == "__main__":
    unittest.main()

