import unittest
from ekart_tracker.notifier import EmailNotifier, WebhookNotifier, DualNotificationManager
from ekart_tracker.models import ShipmentDetails, Milestone

class TestNotifier(unittest.TestCase):

    def setUp(self):
        self.sample_details = ShipmentDetails(
            tracking_id="FMPC_TEST",
            status="Out for Delivery",
            expected_delivery_date="2026-10-31 08:00 PM",
            is_delivered=False,
            reached_nearest_hub=True,
            milestones=[
                Milestone(date_str="Oct 30", time_str="09:00 AM", city="Bengaluru Hub", status_details="Out for Delivery with agent")
            ]
        )

    def test_email_rendering(self):
        notifier = EmailNotifier()
        text = notifier._render_text(self.sample_details, "update")
        self.assertIn("FMPC_TEST", text)
        self.assertIn("Out for Delivery", text)
        self.assertIn("Bengaluru Hub", text)

        html = notifier._render_html(self.sample_details, "update")
        self.assertIn("FMPC_TEST", html)
        self.assertIn("Ekart Logistics", html)
        self.assertIn("Bengaluru Hub", html)

    def test_email_dry_run(self):
        notifier = EmailNotifier()
        success, msg = notifier.send("FMPC_TEST", "Test Subject", self.sample_details)
        self.assertTrue(success)
        self.assertIn("Simulated", msg)

    def test_webhook_dry_run(self):
        notifier = WebhookNotifier()
        success, msg = notifier.send("FMPC_TEST", "Test Subject", self.sample_details)
        self.assertTrue(success)
        self.assertIn("Simulated", msg)

    def test_dual_notification_dispatch(self):
        manager = DualNotificationManager()
        results = manager.notify_status_change(self.sample_details, old_status="In Transit")
        self.assertIn("email", results)
        self.assertIn("webhook", results)
        self.assertTrue(results["email"][0])
        self.assertTrue(results["webhook"][0])

if __name__ == "__main__":
    unittest.main()

