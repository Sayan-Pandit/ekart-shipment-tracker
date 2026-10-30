import asyncio
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands

from .config import config, now_ist
from .storage import TrackerStorage
from .models import ShipmentDetails, Milestone, ShipmentStatus
from .tracker import ShipmentTracker, EkartTrackingError

logger = logging.getLogger("ekart_discord_bot")

EKART_LOGO_URL = "https://static-assets-web.flixcart.com/batman-returns/batman-returns/p/images/logo_lite-cbb357.png"

class ShipmentView(discord.ui.View):
    """Interactive Discord View providing live refresh, portal links, and alert toggles."""
    def __init__(self, tracking_id: str, label: str = "", storage: Optional[TrackerStorage] = None, tracker: Optional[ShipmentTracker] = None):
        super().__init__(timeout=None)
        self.tracking_id = tracking_id.strip().upper()
        self.label = label
        self.storage = storage or TrackerStorage()
        self.tracker = tracker or ShipmentTracker()

        # Link to Official Portal
        url = ShipmentTracker.get_tracking_url(self.tracking_id)
        self.add_item(discord.ui.Button(label="🔎 View on Ekart Portal", url=url, style=discord.ButtonStyle.link, row=0))

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.primary, row=0)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            shipment = self.storage.get_shipment(self.tracking_id)
            is_sim = shipment.is_simulated if shipment else (self.tracking_id.startswith("SIM-") or self.tracking_id.startswith("DEMO-"))
            details = self.tracker.track(self.tracking_id, force_simulated=is_sim, use_cache=False)
            if shipment:
                self.storage.update_shipment_details(details)
            label = self.label or (shipment.label if shipment else "")
            new_embed = create_discord_embed(details, event_type="Live Refresh", label=label)
            await interaction.message.edit(embed=new_embed, view=self)
            await interaction.followup.send(f"✅ Refreshed status for `{self.tracking_id}`!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Refresh failed: `{e}`", ephemeral=True)

    @discord.ui.button(label="🔔 Toggle Alerts", style=discord.ButtonStyle.secondary, row=0)
    async def btn_toggle_alerts(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel_id = str(interaction.channel_id) if interaction.channel_id else None
        if not channel_id:
            await interaction.response.send_message("⚠️ Could not detect channel ID.", ephemeral=True)
            return

        shipment = self.storage.get_shipment(self.tracking_id)
        if not shipment:
            shipment = self.storage.add_shipment(self.tracking_id, label=self.label or f"Package {self.tracking_id}", notify_target=channel_id)
            await interaction.response.send_message(f"🔔 **Subscribed!** You will receive auto-alerts for `{self.tracking_id}` in this channel.", ephemeral=True)
            return

        if shipment.notify_target == channel_id:
            conn = self.storage._get_connection()
            try:
                conn.execute("UPDATE shipments SET notify_target = NULL WHERE tracking_id = ?", (self.tracking_id,))
                conn.commit()
            finally:
                conn.close()
            await interaction.response.send_message(f"🔕 **Alerts Muted:** Notifications for `{self.tracking_id}` turned off in this channel.", ephemeral=True)
        else:
            conn = self.storage._get_connection()
            try:
                conn.execute("UPDATE shipments SET notify_target = ? WHERE tracking_id = ?", (channel_id, self.tracking_id))
                conn.commit()
            finally:
                conn.close()
            await interaction.response.send_message(f"🔔 **Subscribed!** Notifications for `{self.tracking_id}` will now route to this channel.", ephemeral=True)

def get_progress_bar(status: str) -> str:
    norm = ShipmentStatus.normalize(status)
    pct = ShipmentStatus.get_progress_percentage(norm)
    filled = min(5, max(1, pct // 20))
    bar = "🟩" * filled + "⬜" * (5 - filled)
    return f"`[{bar}]` **{pct}%** ({norm})"

def create_discord_embed(details: ShipmentDetails, event_type: str = "Status", label: str = "") -> discord.Embed:
    status_lower = details.status.lower()
    if "delivered" in status_lower:
        color = 0x10B981 # Green
        status_icon = "🏁"
    elif "out for delivery" in status_lower:
        color = 0xF59E0B # Gold / Amber
        status_icon = "🚚"
    elif "nearest hub" in status_lower:
        color = 0x6366F1 # Indigo
        status_icon = "📍"
    elif "in transit" in status_lower:
        color = 0x3B82F6 # Blue
        status_icon = "🚛"
    elif "picked up" in status_lower:
        color = 0x8B5CF6 # Purple
        status_icon = "📦"
    else:
        color = 0x0EA5E9 # Cyan
        status_icon = "📦"

    title = f"📦 Ekart Shipment: {details.tracking_id}"
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_author(name="Ekart Logistics Tracker", icon_url=EKART_LOGO_URL)
    embed.set_thumbnail(url=EKART_LOGO_URL)

    progress_str = get_progress_bar(details.status)
    desc_lines = []
    if label:
        desc_lines.append(f"🏷️ **Item:** `{label}`")
    desc_lines.append(f"**Status:** {status_icon} `{details.status.upper()}`")
    desc_lines.append(f"**Progress:** {progress_str}")
    desc_lines.append(f"**Current Location:** 📍 **{details.current_location}**")
    embed.description = "\n".join(desc_lines)

    # Smart ETA formatting with Discord native relative timestamp
    if details.expected_delivery_epoch:
        eta_val = f"<t:{details.expected_delivery_epoch}:D>\n└ <t:{details.expected_delivery_epoch}:R>"
    elif details.expected_delivery_date:
        eta_val = f"**{details.expected_delivery_date}**"
    else:
        eta_val = "*To be announced*"

    embed.add_field(name="📅 Estimated Delivery", value=eta_val, inline=True)
    embed.add_field(name="📍 Nearest Hub", value="✅ Arrived" if details.reached_nearest_hub else "⏳ On Route", inline=True)
    embed.add_field(name="🏁 Delivered", value="✅ YES" if details.is_delivered else "⏳ In Progress", inline=True)

    # Deduplicated milestones timeline with tree connectors
    milestones = details.deduplicated_milestones
    if milestones:
        timeline_entries = []
        for idx, m in enumerate(reversed(milestones[-5:])):
            prefix = "🟢" if idx == 0 else "•"
            time_display = f"{m.date_str} • {m.time_str}"
            city_display = f"**{m.city}**" if m.city and m.city != "N/A" else ""
            header = f"{prefix} **{time_display}** {f'({city_display})' if city_display else ''}"
            detail = f"  └── *{m.status_details}*"
            timeline_entries.append(f"{header}\n{detail}")
        embed.add_field(name="🚚 Recent Activity Timeline", value="\n".join(timeline_entries), inline=False)
    else:
        embed.add_field(name="🚚 Recent Activity Timeline", value="*No tracking milestones available yet.*", inline=False)

    embed.set_footer(text=f"Ekart Tracker Server • Updated {now_ist().strftime('%I:%M %p IST')}")
    return embed


def setup_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(
        command_prefix=config.discord_prefix,
        intents=intents,
        help_command=None
    )

    storage = TrackerStorage()
    tracker = ShipmentTracker()

    @bot.event
    async def on_ready():
        logger.info("Ekart Discord Bot logged in as %s (ID: %s)", bot.user.name, bot.user.id)
        try:
            synced = await bot.tree.sync()
            logger.info("Synced %d Discord slash commands", len(synced))
        except Exception as e:
            logger.warning("Could not sync slash commands: %s", e)

        # Set bot presence
        activity = discord.Activity(type=discord.ActivityType.watching, name="Ekart Shipments 📦")
        await bot.change_presence(status=discord.Status.online, activity=activity)

    # ------------------ Slash Commands ------------------

    @bot.tree.command(name="track", description="Track an Ekart shipment ID")
    @app_commands.describe(
        tracking_id="Ekart Tracking ID (e.g., FMPC0279658213 or SIM-LAPTOP)",
        label="Optional description or item name",
        simulate="Set to true to track in simulation mode"
    )
    async def slash_track(interaction: discord.Interaction, tracking_id: str, label: str = "", simulate: bool = False):
        clean_id = tracking_id.strip().upper()
        is_sim = simulate or clean_id.startswith("SIM-") or clean_id.startswith("DEMO-")
        await interaction.response.defer(thinking=True)

        storage.add_shipment(
            clean_id,
            label=label or f"Package {clean_id}",
            is_simulated=is_sim,
            notify_target=str(interaction.channel_id) if interaction.channel_id else None
        )
        try:
            details = tracker.track(clean_id, force_simulated=is_sim)
            storage.update_shipment_details(details)
            embed = create_discord_embed(details, event_type="Tracked", label=label)
            await interaction.followup.send(embed=embed, view=ShipmentView(clean_id, label=label, storage=storage, tracker=tracker))
        except Exception as e:
            await interaction.followup.send(f"⚠️ Tracking saved, but live query encountered: `{e}`")

    @bot.tree.command(name="status", description="Get real-time tracking status of a shipment")
    @app_commands.describe(tracking_id="The Ekart Tracking ID to check")
    async def slash_status(interaction: discord.Interaction, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        await interaction.response.defer(thinking=True)

        shipment = storage.get_shipment(clean_id)
        is_sim = shipment.is_simulated if shipment else (clean_id.startswith("SIM-") or clean_id.startswith("DEMO-"))

        try:
            details = tracker.track(clean_id, force_simulated=is_sim)
            if shipment:
                storage.update_shipment_details(details)
            embed = create_discord_embed(details, event_type="Status", label=shipment.label if shipment else "")
            await interaction.followup.send(embed=embed, view=ShipmentView(clean_id, label=shipment.label if shipment else "", storage=storage, tracker=tracker))
        except Exception as e:
            await interaction.followup.send(f"❌ Error querying status for `{clean_id}`: `{e}`")

    @bot.tree.command(name="list", description="List all actively tracked shipments")
    async def slash_list(interaction: discord.Interaction):
        shipments = storage.list_shipments(active_only=True)
        if not shipments:
            await interaction.response.send_message("📦 No shipments are currently tracked. Use `/track <id>` to start tracking!")
            return

        embed = discord.Embed(
            title="📦 Actively Tracked Ekart Shipments",
            color=0x0EA5E9,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name="Ekart Logistics Tracker", icon_url=EKART_LOGO_URL)

        for s in shipments[:25]:
            mode = "🟣 [Simulated]" if s.is_simulated else "🔵 [Live]"
            eta = f"ETA: {s.expected_delivery}" if s.expected_delivery else "ETA: TBD"
            embed.add_field(
                name=f"{s.tracking_id} {mode}",
                value=f"**Label:** {s.label or 'N/A'}\n**Status:** `{s.current_status}`\n*{eta}*",
                inline=False
            )

        embed.set_footer(text=f"Total: {len(shipments)} shipments • Ekart Tracker Server")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="remove", description="Remove a shipment from the tracking list")
    @app_commands.describe(tracking_id="Tracking ID to remove")
    async def slash_remove(interaction: discord.Interaction, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        if storage.remove_shipment(clean_id):
            await interaction.response.send_message(f"✅ Shipment `{clean_id}` has been removed from tracking.")
        else:
            await interaction.response.send_message(f"⚠️ Shipment `{clean_id}` was not found in the database.")

    @bot.tree.command(name="simulate", description="Advance milestone stage of a simulated package (triggers alerts)")
    @app_commands.describe(tracking_id="Tracking ID to advance (e.g. SIM-LAPTOP)")
    async def slash_simulate(interaction: discord.Interaction, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        await interaction.response.defer(thinking=True)

        shipment = storage.get_shipment(clean_id)
        if not shipment:
            shipment = storage.add_shipment(clean_id, "Simulated Package", is_simulated=True)

        old_status = shipment.current_status
        tracker.mock_client.set_stage_from_status(clean_id, old_status)
        new_stage = tracker.mock_client.advance_stage(clean_id)
        details = tracker.mock_client.track(clean_id)
        storage.update_shipment_details(details)

        embed = create_discord_embed(details, event_type=f"Stage Advanced (Step {new_stage})", label=shipment.label)
        await interaction.followup.send(
            content=f"🔔 **Milestone Advanced:** `{old_status}` ➔ `{details.status}`",
            embed=embed,
            view=ShipmentView(clean_id, label=shipment.label if shipment else "", storage=storage, tracker=tracker)
        )

    @bot.tree.command(name="notifytest", description="Send a test notification embed to verify Discord channel alerts")
    async def slash_notify_test(interaction: discord.Interaction):
        sample = ShipmentDetails(
            tracking_id="TEST_FMPC999",
            status="Out for Delivery",
            expected_delivery_date=datetime.now().strftime("%Y-%m-%d 08:00 PM"),
            is_delivered=False,
            reached_nearest_hub=True,
            milestones=[
                Milestone(date_str="Oct 30, 2026", time_str="10:00 AM", city="Mumbai Hub", status_details="Item Bagged and Dispatched"),
                Milestone(date_str="Oct 30, 2026", time_str="03:00 PM", city="Bengaluru Hub", status_details="Out for Delivery with agent")
            ]
        )
        embed = create_discord_embed(sample, event_type="Channel Test Alert", label="Test Package")
        await interaction.response.send_message(content="✅ **Dual Notification Test - Discord Channel Alert:**", embed=embed)

    @bot.tree.command(name="stats", description="View system and tracking metrics")
    async def slash_stats(interaction: discord.Interaction):
        stats = storage.get_stats()
        embed = discord.Embed(title="📊 Ekart Tracker Metrics", color=0x3B82F6, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=EKART_LOGO_URL)
        embed.add_field(name="📦 Active Shipments", value=str(stats.get("active_shipments", 0)), inline=True)
        embed.add_field(name="✅ Total Tracked", value=str(stats.get("total_shipments", 0)), inline=True)
        embed.add_field(name="🏁 Delivered", value=str(stats.get("delivered_shipments", 0)), inline=True)
        embed.add_field(name="🔔 Notifications Sent", value=str(stats.get("total_notifications", 0)), inline=True)
        embed.add_field(name="⏱️ Poll Interval", value=f"{config.poll_interval}s", inline=True)
        embed.set_footer(text="Ekart Tracker Server • 24/7 Monitoring")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="help", description="Show Ekart Tracker Discord Bot commands")
    async def slash_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="📦 Ekart Logistics Tracker - Discord Bot Commands",
            color=0x3B82F6,
            description="Track Flipkart & Ekart packages with live status updates and dual notifications."
        )
        embed.set_thumbnail(url=EKART_LOGO_URL)
        embed.add_field(name="/track `<id>` `[label]` `[simulate]`", value="Add a shipment to the continuous monitoring pool.", inline=False)
        embed.add_field(name="/status `<id>`", value="Query current live status and milestones for a package.", inline=False)
        embed.add_field(name="/list", value="View all actively tracked shipments.", inline=False)
        embed.add_field(name="/simulate `<id>`", value="Advance a simulated package to test milestone alerts.", inline=False)
        embed.add_field(name="/remove `<id>`", value="Remove a package from tracking.", inline=False)
        embed.add_field(name="/notifytest", value="Send a sample notification embed to test channel integration.", inline=False)
        embed.set_footer(text=f"Prefix commands also supported using prefix '{config.discord_prefix}' (e.g. {config.discord_prefix}track)")
        await interaction.response.send_message(embed=embed)

    # ------------------ Prefix Commands ------------------

    @bot.command(name="track", aliases=["add"])
    async def cmd_track(ctx: commands.Context, tracking_id: str, *, label: str = ""):
        clean_id = tracking_id.strip().upper()
        is_sim = clean_id.startswith("SIM-") or clean_id.startswith("DEMO-")
        storage.add_shipment(
            clean_id,
            label=label or f"Package {clean_id}",
            is_simulated=is_sim,
            notify_target=str(ctx.channel.id) if ctx.channel else None
        )
        try:
            details = tracker.track(clean_id, force_simulated=is_sim)
            storage.update_shipment_details(details)
            embed = create_discord_embed(details, event_type="Tracked", label=label)
            await ctx.send(embed=embed, view=ShipmentView(clean_id, label=label, storage=storage, tracker=tracker))
        except Exception as e:
            await ctx.send(f"⚠️ Tracking saved, but live query encountered: `{e}`")

    @bot.command(name="status", aliases=["info"])
    async def cmd_status(ctx: commands.Context, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        shipment = storage.get_shipment(clean_id)
        is_sim = shipment.is_simulated if shipment else (clean_id.startswith("SIM-") or clean_id.startswith("DEMO-"))
        try:
            details = tracker.track(clean_id, force_simulated=is_sim)
            if shipment:
                storage.update_shipment_details(details)
            embed = create_discord_embed(details, event_type="Status", label=shipment.label if shipment else "")
            await ctx.send(embed=embed, view=ShipmentView(clean_id, label=shipment.label if shipment else "", storage=storage, tracker=tracker))
        except Exception as e:
            await ctx.send(f"❌ Error querying status for `{clean_id}`: `{e}`")
        except Exception as e:
            await ctx.send(f"❌ Error querying status for `{clean_id}`: `{e}`")

    @bot.command(name="list")
    async def cmd_list(ctx: commands.Context):
        shipments = storage.list_shipments(active_only=True)
        if not shipments:
            await ctx.send("📦 No shipments are currently tracked. Use `!track <id>` to start tracking!")
            return

        embed = discord.Embed(title="📦 Actively Tracked Ekart Shipments", color=0x0EA5E9, timestamp=datetime.now(timezone.utc))
        for s in shipments[:25]:
            mode = "🟣 [Simulated]" if s.is_simulated else "🔵 [Live]"
            eta = f"ETA: {s.expected_delivery}" if s.expected_delivery else "ETA: TBD"
            embed.add_field(name=f"{s.tracking_id} {mode}", value=f"**Label:** {s.label or 'N/A'}\n**Status:** `{s.current_status}`\n*{eta}*", inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="simulate")
    async def cmd_simulate(ctx: commands.Context, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        shipment = storage.get_shipment(clean_id)
        if not shipment:
            shipment = storage.add_shipment(clean_id, "Simulated Package", is_simulated=True)

        old_status = shipment.current_status
        tracker.mock_client.set_stage_from_status(clean_id, old_status)
        new_stage = tracker.mock_client.advance_stage(clean_id)
        details = tracker.mock_client.track(clean_id)
        storage.update_shipment_details(details)

        embed = create_discord_embed(details, event_type=f"Stage Advanced (Step {new_stage})", label=shipment.label)
        await ctx.send(
            content=f"🔔 **Milestone Advanced:** `{old_status}` ➔ `{details.status}`",
            embed=embed,
            view=ShipmentView(clean_id, label=shipment.label if shipment else "", storage=storage, tracker=tracker)
        )

    @bot.command(name="remove", aliases=["delete"])
    async def cmd_remove(ctx: commands.Context, tracking_id: str):
        clean_id = tracking_id.strip().upper()
        if storage.remove_shipment(clean_id):
            await ctx.send(f"✅ Shipment `{clean_id}` has been removed from tracking.")
        else:
            await ctx.send(f"⚠️ Shipment `{clean_id}` was not found.")

    @bot.command(name="notifytest")
    async def cmd_notifytest(ctx: commands.Context):
        sample = ShipmentDetails(
            tracking_id="TEST_FMPC999",
            status="Out for Delivery",
            expected_delivery_date=datetime.now().strftime("%Y-%m-%d 08:00 PM"),
            is_delivered=False,
            reached_nearest_hub=True,
            milestones=[
                Milestone(date_str="Oct 30, 2026", time_str="10:00 AM", city="Mumbai Hub", status_details="Item Bagged and Dispatched"),
                Milestone(date_str="Oct 30, 2026", time_str="03:00 PM", city="Bengaluru Hub", status_details="Out for Delivery with agent")
            ]
        )
        embed = create_discord_embed(sample, event_type="Channel Test Alert", label="Test Package")
        await ctx.send(content="✅ **Dual Notification Test - Discord Channel Alert:**", embed=embed)

    @bot.command(name="stats")
    async def cmd_stats(ctx: commands.Context):
        stats = storage.get_stats()
        embed = discord.Embed(title="📊 Ekart Tracker Metrics", color=0x3B82F6, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=EKART_LOGO_URL)
        embed.add_field(name="📦 Active Shipments", value=str(stats.get("active_shipments", 0)), inline=True)
        embed.add_field(name="✅ Total Tracked", value=str(stats.get("total_shipments", 0)), inline=True)
        embed.add_field(name="🏁 Delivered", value=str(stats.get("delivered_shipments", 0)), inline=True)
        embed.add_field(name="🔔 Notifications Sent", value=str(stats.get("total_notifications", 0)), inline=True)
        embed.add_field(name="⏱️ Poll Interval", value=f"{config.poll_interval}s", inline=True)
        embed.set_footer(text="Ekart Tracker Server • 24/7 Monitoring")
        await ctx.send(embed=embed)

    @bot.command(name="help")
    async def cmd_help(ctx: commands.Context):
        p = config.discord_prefix
        text = (
            f"**📦 Ekart Logistics Tracker Commands:**\n"
            f"• `{p}track <id> [label]` - Start tracking a package\n"
            f"• `{p}status <id>` - Check live status and timeline\n"
            f"• `{p}list` - List all tracked packages\n"
            f"• `{p}simulate <id>` - Advance milestone for simulated package\n"
            f"• `{p}remove <id>` - Remove package from tracking\n"
            f"• `{p}notifytest` - Send a sample alert embed to this channel\n"
            f"\n*Slash commands (`/track`, `/status`, `/list`, etc.) are also enabled.*"
        )
        await ctx.send(text)

    return bot

async def send_discord_channel_notification(bot: commands.Bot, channel_id: int, details: ShipmentDetails, event_type: str = "Status Update") -> bool:
    """Send an embed notification to a specific Discord channel."""
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            channel = await bot.fetch_channel(channel_id)
        if channel:
            embed = create_discord_embed(details, event_type=event_type)
            await channel.send(embed=embed)
            return True
    except Exception as e:
        logger.error("Failed sending Discord channel notification: %s", e)
    return False

def run_discord_bot():
    """Run the Discord Bot."""
    if not config.discord_bot_token:
        print("[!] DISCORD_BOT_TOKEN is not configured in .env!")
        print("Please set DISCORD_BOT_TOKEN in your .env file or environment variables.")
        return

    bot = setup_bot()
    bot.run(config.discord_bot_token)

if __name__ == "__main__":
    run_discord_bot()

