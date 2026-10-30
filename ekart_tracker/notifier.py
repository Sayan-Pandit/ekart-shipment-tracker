import smtplib
import json
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import requests

from .config import config
from .models import NotificationRecord, ShipmentDetails, Milestone

logger = logging.getLogger(__name__)

class EmailNotifier:
    """Sends email notifications via SMTP with rich HTML & plain text formatting."""

    def __init__(self):
        self.host = config.smtp_host
        self.port = config.smtp_port
        self.use_tls = config.smtp_use_tls
        self.user = config.smtp_user
        self.password = config.smtp_password
        self.from_addr = config.email_from
        self.to_addr = config.email_to

    def is_configured(self) -> bool:
        return bool(self.host and self.to_addr and self.user and self.password)

    def send(self, tracking_id: str, subject: str, details: ShipmentDetails, event_type: str = "update") -> Tuple[bool, str]:
        """
        Send an email notification. Returns (success, status_or_error_message).
        If SMTP is not fully configured, operates in Dry-Run mode and logs the full email.
        """
        html_content = self._render_html(details, event_type)
        text_content = self._render_text(details, event_type)

        if not self.is_configured():
            logger.info("[Email Dry-Run] SMTP credentials not set. Simulated for %s: Status=%s", tracking_id, details.status)
            return True, "Simulated (SMTP credentials not configured in .env)"

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_addr
            msg["To"] = self.to_addr

            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=15)
                if self.use_tls:
                    server.starttls()

            if self.user and self.password:
                server.login(self.user, self.password)

            server.sendmail(self.from_addr, [self.to_addr], msg.as_string())
            server.quit()
            logger.info("Email notification successfully sent for %s", tracking_id)
            return True, "Sent"

        except Exception as e:
            logger.error("Failed to send email notification: %s", e)
            return False, f"SMTP Error: {str(e)}"

    def _render_text(self, details: ShipmentDetails, event_type: str) -> str:
        lines = [
            "========================================",
            f" EKART LOGISTICS - SHIPMENT UPDATE",
            "========================================",
            f"Tracking ID: {details.tracking_id}",
            f"Current Status: {details.status}",
            f"Expected Delivery: {details.expected_delivery_date or 'Not specified'}",
            f"Delivered: {'Yes' if details.is_delivered else 'No'}",
            "",
            "Recent Journey Milestones:",
            "----------------------------------------"
        ]
        for m in reversed(details.milestones[-5:]):
            lines.append(f"- [{m.date_str} {m.time_str}] ({m.city}): {m.status_details}")
        lines.append("========================================")
        return "\n".join(lines)

    def _render_html(self, details: ShipmentDetails, event_type: str) -> str:
        color_map = {
            "Delivered": "#10B981", # Green
            "Out for Delivery": "#F59E0B", # Orange
            "In Transit": "#3B82F6", # Blue
            "Reached Nearest Hub": "#6366F1", # Indigo
            "Picked Up": "#8B5CF6", # Purple
        }
        badge_color = color_map.get(details.status, "#4F46E5")

        milestone_rows = ""
        for m in reversed(details.milestones[-6:]):
            milestone_rows += f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 10px 12px; font-size: 13px; color: #4b5563;">{m.date_str} {m.time_str}</td>
                <td style="padding: 10px 12px; font-size: 13px; font-weight: 600; color: #111827;">{m.city}</td>
                <td style="padding: 10px 12px; font-size: 13px; color: #374151;">{m.status_details}</td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; margin: 0; padding: 24px; }}
            .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e5e7eb; }}
            .header {{ background: #1e3a8a; color: white; padding: 24px; text-align: center; }}
            .content {{ padding: 24px; }}
            .badge {{ display: inline-block; background-color: {badge_color}; color: white; padding: 6px 16px; border-radius: 20px; font-weight: bold; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; }}
            .info-box {{ background: #f9fafb; border-radius: 8px; padding: 16px; margin: 20px 0; border: 1px solid #e5e7eb; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
            th {{ background: #f3f4f6; text-align: left; padding: 10px 12px; font-size: 12px; text-transform: uppercase; color: #6b7280; }}
            .footer {{ text-align: center; font-size: 12px; color: #9ca3af; padding: 16px 24px; border-top: 1px solid #e5e7eb; }}
          </style>
        </head>
        <body>
          <div class="card">
            <div class="header">
              <h2 style="margin: 0; font-size: 20px; font-weight: 700;">📦 Ekart Logistics Tracker</h2>
              <p style="margin: 6px 0 0; opacity: 0.85; font-size: 14px;">Shipment Status Notification</p>
            </div>
            <div class="content">
              <div style="text-align: center; margin-bottom: 20px;">
                <span class="badge">{details.status}</span>
                <h3 style="margin: 12px 0 4px; font-size: 18px; color: #111827;">Tracking ID: {details.tracking_id}</h3>
              </div>
              <div class="info-box">
                <p style="margin: 4px 0;"><strong>Estimated Delivery:</strong> {details.expected_delivery_date or 'To be announced'}</p>
                <p style="margin: 4px 0;"><strong>Delivered:</strong> {'✅ Yes' if details.is_delivered else '⏳ In Progress'}</p>
                <p style="margin: 4px 0;"><strong>Nearest Hub:</strong> {'Reached' if details.reached_nearest_hub else 'In Transit'}</p>
              </div>
              <h4 style="margin: 20px 0 8px; font-size: 15px; color: #1f2937;">Activity Timeline</h4>
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Location</th>
                    <th>Milestone Details</th>
                  </tr>
                </thead>
                <tbody>
                  {milestone_rows}
                </tbody>
              </table>
            </div>
            <div class="footer">
              Automated alert by Ekart Shipment Tracker Server &bull; {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
          </div>
        </body>
        </html>
        """


class WebhookNotifier:
    """Sends notifications to HTTP webhooks (Discord, Slack, Telegram, or custom) or Discord Bot Channel."""

    def __init__(self):
        self.webhook_url = config.webhook_url
        self.discord_bot_token = config.discord_bot_token
        self.discord_channel_id = config.discord_channel_id
        self.discord_user_id = config.discord_user_id
        self.telegram_bot_token = config.telegram_bot_token
        self.telegram_chat_id = config.telegram_chat_id

    def is_configured(self) -> bool:
        return bool(
            self.webhook_url or 
            (self.discord_bot_token and (self.discord_channel_id or self.discord_user_id)) or 
            (self.telegram_bot_token and self.telegram_chat_id)
        )

    def send(self, tracking_id: str, subject: str, details: ShipmentDetails, event_type: str = "update", notify_target: Optional[str] = None) -> Tuple[bool, str]:
        """
        Send a notification to Discord (Bot/Webhook) or Telegram/generic webhook.
        If not configured, operates in Dry-Run mode.
        """
        if not self.is_configured() and not notify_target:
            logger.info("[Discord/Webhook Dry-Run] Neither Discord Bot nor Webhook URL configured. Simulated for %s", tracking_id)
            return True, "Simulated (Discord/Webhook credentials not set in .env)"

        # Priority 1: Direct Discord Bot Channel / DM Message
        if self.discord_bot_token and (notify_target or self.discord_channel_id or self.discord_user_id):
            return self._send_discord_bot_api(details, target_channel_id=notify_target)

        # Priority 2: Telegram Bot
        if self.telegram_bot_token and self.telegram_chat_id:
            return self._send_telegram(details)

        # Priority 3: Standard Webhook (Discord / Slack / Generic)
        return self._send_http_webhook(details, subject)

    def _send_discord_bot_api(self, details: ShipmentDetails, target_channel_id: Optional[str] = None) -> Tuple[bool, str]:
        headers = {
            "Authorization": f"Bot {self.discord_bot_token}",
            "Content-Type": "application/json"
        }

        channel_id = target_channel_id or self.discord_channel_id
        # If user ID is configured, resolve/create a private DM channel
        if not channel_id and self.discord_user_id:
            try:
                dm_res = requests.post(
                    "https://discord.com/api/v10/users/@me/channels",
                    json={"recipient_id": self.discord_user_id},
                    headers=headers,
                    timeout=10
                )
                if dm_res.status_code in (200, 201):
                    channel_id = dm_res.json().get("id")
                else:
                    logger.warning("Could not open DM channel with user %s: %s", self.discord_user_id, dm_res.text)
            except Exception as e:
                logger.warning("Error creating DM channel: %s", e)

        if not channel_id:
            return False, "Neither DISCORD_CHANNEL_ID nor valid DISCORD_USER_ID configured"

        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        
        status_lower = details.status.lower()
        color = 0x10B981 if "delivered" in status_lower else (
            0xF59E0B if "out for delivery" in status_lower else (
                0x6366F1 if "hub" in status_lower else 0x3B82F6
            )
        )

        timeline_text = ""
        if details.milestones:
            for m in reversed(details.milestones[-4:]):
                timeline_text += f"• **{m.date_str} {m.time_str}** ({m.city})\n  └ *{m.status_details}*\n"
        else:
            timeline_text = "*No milestones recorded yet.*"

        payload = {
            "content": f"🔔 **Ekart Shipment Status Alert:** `{details.tracking_id}` is now **{details.status}**",
            "embeds": [{
                "title": f"📦 Ekart Logistics: {details.tracking_id}",
                "color": color,
                "fields": [
                    {"name": "Status", "value": f"`{details.status}`", "inline": True},
                    {"name": "Estimated Delivery", "value": details.expected_delivery_date or "To be announced", "inline": True},
                    {"name": "Delivered", "value": "✅ YES" if details.is_delivered else "⏳ In Progress", "inline": True},
                    {"name": "Recent Milestones", "value": timeline_text, "inline": False}
                ],
                "footer": {"text": "Ekart Shipment Tracker • Automated Alert"},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            logger.info("Notification sent via Discord Bot API for %s", details.tracking_id)
            return True, "Sent via Discord Bot API"
        except Exception as e:
            logger.error("Failed sending Discord Bot API notification: %s", e)
            return False, f"Discord Bot API Error: {str(e)}"

    def _send_telegram(self, details: ShipmentDetails) -> Tuple[bool, str]:
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        text = (
            f"📦 *Ekart Shipment Update*\n"
            f"*ID:* `{details.tracking_id}`\n"
            f"*Status:* *{details.status}*\n"
            f"*ETA:* {details.expected_delivery_date or 'N/A'}\n"
            f"*Delivered:* {'✅ Yes' if details.is_delivered else '⏳ In Progress'}\n\n"
        )
        if details.milestones:
            latest = details.milestones[-1]
            text += f"📍 *Latest:* {latest.city} - {latest.status_details} ({latest.date_str} {latest.time_str})"

        try:
            resp = requests.post(url, json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
            resp.raise_for_status()
            return True, "Sent to Telegram"
        except Exception as e:
            logger.error("Failed sending Telegram message: %s", e)
            return False, f"Telegram Error: {str(e)}"

    def _send_http_webhook(self, details: ShipmentDetails, subject: str) -> Tuple[bool, str]:
        # Support Discord Embed format if discord.com in URL
        if "discord.com" in self.webhook_url or "discordapp.com" in self.webhook_url:
            payload = {
                "username": "Ekart Tracker",
                "avatar_url": "https://static-assets-web.flixcart.com/batman-returns/batman-returns/p/images/logo_lite-cbb357.png",
                "embeds": [{
                    "title": f"📦 Shipment Alert: {details.tracking_id}",
                    "description": f"**Status:** {details.status}\n**Estimated Delivery:** {details.expected_delivery_date or 'N/A'}",
                    "color": 3066993 if details.is_delivered else 3447003,
                    "fields": [
                        {"name": "Latest Hub / City", "value": details.milestones[-1].city if details.milestones else "N/A", "inline": True},
                        {"name": "Delivered", "value": "✅ Yes" if details.is_delivered else "⏳ No", "inline": True},
                        {"name": "Latest Update", "value": details.milestones[-1].status_details if details.milestones else "Pending", "inline": False}
                    ],
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
        else:
            # Generic JSON Webhook
            payload = {
                "event": "ekart_shipment_update",
                "tracking_id": details.tracking_id,
                "status": details.status,
                "expected_delivery_date": details.expected_delivery_date,
                "is_delivered": details.is_delivered,
                "reached_nearest_hub": details.reached_nearest_hub,
                "milestones": [m.to_dict() for m in details.milestones],
                "timestamp": datetime.now().isoformat()
            }

        try:
            resp = requests.post(self.webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            resp.raise_for_status()
            return True, "Sent to Webhook"
        except Exception as e:
            logger.error("Failed sending Webhook notification: %s", e)
            return False, f"Webhook Error: {str(e)}"


class DualNotificationManager:
    """
    Manages notifications across both channels:
    1. Email (SMTP)
    2. Webhook (HTTP / Telegram / Discord)
    """

    def __init__(self, storage=None):
        self.email_notifier = EmailNotifier()
        self.webhook_notifier = WebhookNotifier()
        self.storage = storage

    def notify_status_change(self, details: ShipmentDetails, old_status: Optional[str] = None, notify_target: Optional[str] = None) -> Dict[str, Tuple[bool, str]]:
        """
        Dispatches alerts across both channels whenever a shipment status changes.
        """
        subject = f"📦 Ekart Update: {details.tracking_id} is now [{details.status}]"
        results: Dict[str, Tuple[bool, str]] = {}

        # 1. Email Channel
        if config.email_enabled:
            email_ok, email_msg = self.email_notifier.send(details.tracking_id, subject, details, event_type="status_change")
            results["email"] = (email_ok, email_msg)
            if self.storage:
                self.storage.log_notification(NotificationRecord(
                    id=None,
                    tracking_id=details.tracking_id,
                    channel="email",
                    event_type="status_change",
                    message=f"Status: {details.status} | {email_msg}",
                    status="sent" if email_ok and "Simulated" not in email_msg else ("simulated" if email_ok else "failed"),
                    created_at=datetime.now().isoformat(),
                    error_message=None if email_ok else email_msg
                ))

        # 2. Webhook / Discord Channel
        if config.webhook_enabled:
            wh_ok, wh_msg = self.webhook_notifier.send(details.tracking_id, subject, details, event_type="status_change", notify_target=notify_target)
            results["webhook"] = (wh_ok, wh_msg)
            if self.storage:
                self.storage.log_notification(NotificationRecord(
                    id=None,
                    tracking_id=details.tracking_id,
                    channel="webhook",
                    event_type="status_change",
                    message=f"Status: {details.status} | {wh_msg}",
                    status="sent" if wh_ok and "Simulated" not in wh_msg else ("simulated" if wh_ok else "failed"),
                    created_at=datetime.now().isoformat(),
                    error_message=None if wh_ok else wh_msg
                ))

        return results

    def send_test_notifications(self, tracking_id: str = "FMPC0279658213") -> Dict[str, Tuple[bool, str]]:
        """Trigger immediate test notifications to verify both channels."""
        test_milestones = [
            Milestone(date_str="Oct 30, 2026", time_str="10:00 AM", city="Mumbai Sort Center", status_details="Item Bagged and Dispatched", timestamp=int(datetime.now().timestamp() * 1000) - 3600000),
            Milestone(date_str="Oct 30, 2026", time_str="02:30 PM", city="Bengaluru Hub", status_details="Out for Delivery with agent", timestamp=int(datetime.now().timestamp() * 1000))
        ]
        sample_details = ShipmentDetails(
            tracking_id=tracking_id,
            status="Out for Delivery",
            expected_delivery_date=datetime.now().strftime("%Y-%m-%d 08:00 PM"),
            is_delivered=False,
            fa_shipment=True,
            reached_nearest_hub=True,
            milestones=test_milestones
        )
        return self.notify_status_change(sample_details)
