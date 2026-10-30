import sys
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

# Ensure terminal UTF-8 encoding support
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
from rich.layout import Layout
from rich.live import Live
from rich import box

from .models import TrackedShipment, Milestone, NotificationRecord, ShipmentDetails

console = Console(force_terminal=True, legacy_windows=False)

STATUS_COLOR_MAP = {
    "Delivered": "bold green",
    "Out for Delivery": "bold yellow",
    "Reached Nearest Hub": "bold magenta",
    "In Transit": "bold cyan",
    "Picked Up": "bold blue",
    "Order Created": "dim white",
    "Delivery Attempted / Failed": "bold red",
    "Returned / Cancelled": "bold red",
    "Status Pending / Not Found": "dim yellow",
    "Initialized": "dim cyan"
}

def get_status_style(status_str: str) -> str:
    for key, color in STATUS_COLOR_MAP.items():
        if key.lower() in status_str.lower():
            return color
    return "white"

def render_banner(server_status: Optional[Dict[str, Any]] = None) -> Panel:
    title_text = Text()
    title_text.append("📦 EKART LOGISTICS SHIPMENT TRACKER", style="bold cyan")
    title_text.append(" | ", style="dim")
    title_text.append("Platform: ", style="dim")
    title_text.append("Server Daemon", style="bold green")
    title_text.append(" | ", style="dim")
    title_text.append("Notifications: ", style="dim")
    title_text.append("Both (Email + Webhook)", style="bold yellow")
    title_text.append(" | ", style="dim")
    title_text.append("Interface: ", style="dim")
    title_text.append("Terminal", style="bold magenta")

    if server_status:
        st = server_status.get("status", "unknown").upper()
        active_cnt = server_status.get("active_shipments_count", 0)
        notif = server_status.get("notifications", {})
        email_st = "ON" if notif.get("email_enabled") else "OFF"
        wh_st = "ON" if notif.get("webhook_enabled") else "OFF"
        subtitle = f"Server: [bold green]{st}[/] • Active: [bold white]{active_cnt}[/] • Channels: [blue]Email:[{email_st}][/] | [yellow]Webhook:[{wh_st}][/]"
    else:
        subtitle = "Terminal Command & Control Center"

    return Panel(title_text, subtitle=subtitle, box=box.ROUNDED, style="cyan")

def render_shipments_table(shipments: List[TrackedShipment]) -> Table:
    table = Table(
        title="Tracked Ekart Shipments",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=True
    )

    table.add_column("Tracking ID", style="bold white", no_wrap=True)
    table.add_column("Label / Description", style="italic")
    table.add_column("Mode", justify="center")
    table.add_column("Current Status", justify="center")
    table.add_column("Milestones", justify="center")
    table.add_column("Estimated Delivery", justify="center")
    table.add_column("Last Checked", justify="center", style="dim")

    if not shipments:
        table.add_row("-", "No shipments currently tracked. Use 'add' command.", "-", "-", "-", "-", "-")
        return table

    for s in shipments:
        mode_str = "[bold magenta]SIMULATED[/]" if s.is_simulated else "[bold blue]LIVE API[/]"
        status_style = get_status_style(s.current_status)
        status_text = f"[{status_style}]{s.current_status}[/]"
        milestone_count = f"[bold cyan]{len(s.milestones)}[/] steps"
        eta = s.expected_delivery or "[dim]N/A[/]"
        
        last_chk = "[dim]Never[/]"
        if s.last_checked_at:
            try:
                dt = datetime.fromisoformat(s.last_checked_at)
                last_chk = dt.strftime("%H:%M:%S")
            except Exception:
                last_chk = s.last_checked_at[:19]

        table.add_row(
            s.tracking_id,
            s.label or "-",
            mode_str,
            status_text,
            milestone_count,
            eta,
            last_chk
        )

    return table

def render_shipment_details(details: ShipmentDetails, label: str = "") -> None:
    status_style = get_status_style(details.status)

    header = Panel(
        Text.from_markup(
            f"[bold white]Tracking ID:[/] [cyan]{details.tracking_id}[/]\n"
            f"[bold white]Label:[/] {label or 'N/A'}\n"
            f"[bold white]Current Status:[/] [{status_style}]{details.status}[/]\n"
            f"[bold white]Delivered:[/] {'[bold green]YES[/]' if details.is_delivered else '[yellow]NO (In Progress)[/]'}\n"
            f"[bold white]Nearest Hub Reached:[/] {'[bold green]YES[/]' if details.reached_nearest_hub else '[dim]NO[/]'}\n"
            f"[bold white]Expected Delivery:[/] [bold]{details.expected_delivery_date or 'To be announced'}[/]"
        ),
        title=f"📦 Shipment Journey: {details.tracking_id}",
        box=box.ROUNDED,
        style="cyan"
    )
    console.print(header)

    # Journey Tree
    tree = Tree(f"[bold cyan]🚚 Tracking Timeline ({len(details.milestones)} events)[/]")
    if not details.milestones:
        tree.add("[dim italic]No milestone events reported yet from Ekart network.[/]")
    else:
        for idx, m in enumerate(reversed(details.milestones), 1):
            is_latest = (idx == 1)
            bullet_style = "bold green" if is_latest else "cyan"
            m_node = tree.add(
                f"[{bullet_style}]●[/] [bold white]{m.date_str} {m.time_str}[/] • [bold yellow]{m.city}[/] {'(LATEST)' if is_latest else ''}"
            )
            m_node.add(f"[italic]{m.status_details}[/]")

    console.print(tree)
    console.print()

def render_notifications_table(records: List[NotificationRecord]) -> Table:
    table = Table(
        title="🔔 Dual-Channel Notification History (Email & Webhook)",
        box=box.ROUNDED,
        header_style="bold yellow",
        show_lines=True
    )

    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Tracking ID", style="bold white", no_wrap=True)
    table.add_column("Channel", justify="center")
    table.add_column("Event", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Message / Summary")

    if not records:
        table.add_row("-", "-", "-", "-", "-", "No notification dispatches recorded yet.")
        return table

    for r in records:
        channel_str = "[bold blue]EMAIL[/]" if r.channel == "email" else "[bold yellow]WEBHOOK[/]"
        
        if r.status == "sent":
            status_str = "[bold green]SENT[/]"
        elif r.status == "simulated":
            status_str = "[cyan]SIMULATED (Dry-Run)[/]"
        else:
            status_str = f"[bold red]FAILED ({r.error_message or 'Error'})[/]"

        time_str = r.created_at[:19].replace("T", " ") if r.created_at else "-"

        table.add_row(
            time_str,
            r.tracking_id,
            channel_str,
            r.event_type,
            status_str,
            r.message
        )

    return table
