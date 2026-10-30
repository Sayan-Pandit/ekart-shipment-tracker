import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from typing import Optional, Dict, Any, List

# Ensure terminal UTF-8 encoding support
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
import requests

from .config import config
from .storage import TrackerStorage
from .models import ShipmentDetails
from .tracker import ShipmentTracker, EkartTrackingError
from .notifier import DualNotificationManager
from .tui import (
    console,
    render_banner,
    render_shipments_table,
    render_shipment_details,
    render_notifications_table
)

SERVER_BASE_URL = f"http://{config.host}:{config.port}"

def get_server_status_api() -> Optional[Dict[str, Any]]:
    """Try to reach server REST API."""
    try:
        resp = requests.get(f"{SERVER_BASE_URL}/api/status", timeout=1.5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

def is_server_process_running() -> Optional[int]:
    if not config.pid_file.exists():
        return None
    try:
        with open(config.pid_file, "r") as f:
            pid = int(f.read().strip())
        # Check process in Windows / POSIX
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process != 0:
                kernel32.CloseHandle(process)
                return pid
        else:
            os.kill(pid, 0)
            return pid
    except Exception:
        pass
    return None

@click.group()
def cli():
    """Ekart Logistics Shipment Tracker - Terminal Command Line Interface."""
    pass

@cli.group()
def server():
    """Manage the background tracking server daemon."""
    pass

@cli.group()
def bot():
    """Manage and run the Ekart Discord Bot."""
    pass

@bot.command("start")
def bot_start():
    """Start the Ekart Discord Bot."""
    if not config.discord_bot_token:
        console.print("[bold red]Error:[/] DISCORD_BOT_TOKEN is not set in .env!")
        console.print("Please set your Discord Bot token in .env (see .env.example) to start the Discord Bot.")
        return
    console.print(render_banner())
    console.print(f"[bold green]Starting Ekart Discord Bot with prefix '{config.discord_prefix}'...[/]")
    from .bot import run_discord_bot
    run_discord_bot()

@bot.command("status")
def bot_status():
    """Check Discord Bot configuration and channel settings."""
    status = get_server_status_api()
    console.print(render_banner(status))
    console.print("[bold cyan]Discord Bot Configuration:[/]")
    console.print(f"  • Bot Enabled: {'[bold green]YES[/]' if config.discord_bot_enabled else '[dim]NO[/]'}")
    console.print(f"  • Bot Token: {'[bold green]CONFIGURED[/]' if config.discord_bot_token else '[bold yellow]NOT SET (Add to .env)[/]'}")
    console.print(f"  • Notification Channel ID: [bold white]{config.discord_channel_id or 'Not Set'}[/]")
    console.print(f"  • Command Prefix: [bold cyan]{config.discord_prefix}[/]")
    console.print(f"  • Webhook Fallback URL: {'[green]Configured[/]' if config.webhook_url else '[dim]Not Set[/]'}")
    console.print("\n[dim]To launch the Discord Bot, run:[/] [bold cyan]ekart-tracker bot start[/]")

@server.command("start")
@click.option("--daemon/--no-daemon", default=False, help="Run as background process")
def server_start(daemon: bool):
    """Start the Ekart Tracker server daemon."""
    status = get_server_status_api()
    if status:
        console.print(f"[bold yellow]Server is already running on {SERVER_BASE_URL} (Uptime: {status.get('uptime_seconds')}s)[/]")
        return

    if daemon:
        console.print("[bold cyan]Starting server daemon in the background...[/]")
        
        if os.name == "nt":
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            executable = pythonw if os.path.exists(pythonw) else sys.executable
            cmd = [executable, "-m", "ekart_tracker.server"]
            process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW if os.path.exists(pythonw) else (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS),
                cwd=str(Path.cwd())
            )
        else:
            cmd = [sys.executable, "-m", "ekart_tracker.server"]
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(Path.cwd()),
                start_new_session=True
            )
        
        # Wait a moment for server to bind
        time.sleep(1.5)
        status = get_server_status_api()
        if status:
            console.print(f"[bold green]✓ Server daemon successfully started on {SERVER_BASE_URL}[/]")
        else:
            console.print("[yellow]Server started in background. Check with 'ekart-tracker server status'.[/]")
    else:
        console.print(render_banner())
        console.print(f"[bold green]Starting Ekart Tracker Server on {SERVER_BASE_URL} (Press Ctrl+C to stop)...[/]\n")
        from .server import run_server
        try:
            run_server()
        except KeyboardInterrupt:
            console.print("\n[yellow]Server stopped by user.[/]")

@server.command("stop")
def server_stop():
    """Stop the background server daemon."""
    pid = is_server_process_running()
    if not pid:
        status = get_server_status_api()
        if not status:
            console.print("[yellow]Server is not running.[/]")
            return
    
    if pid:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            if config.pid_file.exists():
                config.pid_file.unlink()
            console.print(f"[bold green]✓ Stopped server daemon (PID {pid}).[/]")
            return
        except Exception as e:
            console.print(f"[red]Failed to stop process {pid}: {e}[/]")

    console.print("[yellow]Could not terminate server directly via PID.[/]")

@server.command("status")
def server_status():
    """Check background server health, uptime, and notification settings."""
    status = get_server_status_api()
    console.print(render_banner(status))
    if status:
        console.print(f"[bold green]● Server Status: RUNNING[/] on [cyan]{SERVER_BASE_URL}[/]")
        console.print(f"  • Uptime: [bold white]{status.get('uptime_seconds')} seconds[/]")
        console.print(f"  • Active Tracked Shipments: [bold white]{status.get('active_shipments_count')}[/]")
        console.print(f"  • Polling Interval: [bold white]{status.get('poll_interval_seconds')}s[/]")
        notif = status.get("notifications", {})
        console.print("  • Notification Channels:")
        console.print(f"     - Email (SMTP): {'[bold green]ENABLED[/]' if notif.get('email_enabled') else '[dim]DISABLED[/]'} ({'Configured' if notif.get('email_configured') else 'Dry-Run / Unset'})")
        console.print(f"     - Webhook: {'[bold green]ENABLED[/]' if notif.get('webhook_enabled') else '[dim]DISABLED[/]'} ({'Configured' if notif.get('webhook_configured') else 'Dry-Run / Unset'})")
    else:
        console.print("[bold red]● Server Status: STOPPED[/]")
        console.print("Run '[bold cyan]python -m ekart_tracker.cli server start[/]' to start tracking.")

@cli.command("add")
@click.argument("tracking_id")
@click.option("--label", "-l", default="", help="Friendly description or package name")
@click.option("--simulate", "-s", is_flag=True, default=False, help="Track in simulation/demo mode")
def add_shipment(tracking_id: str, label: str, simulate: bool):
    """Add a new Ekart shipment to track."""
    clean_id = tracking_id.strip().upper()
    console.print(f"[cyan]Adding package [bold white]{clean_id}[/]...[/]")

    # Check if server is running
    status = get_server_status_api()
    if status:
        try:
            resp = requests.post(f"{SERVER_BASE_URL}/api/shipments", json={
                "tracking_id": clean_id,
                "label": label,
                "is_simulated": simulate
            }, timeout=15)
            if resp.status_code in (200, 201):
                data = resp.json()
                console.print(f"[bold green]✓ Successfully added to server tracking pool![/]")
                console.print(f"  Status: [bold cyan]{data.get('current_status', 'Pending')}[/]")
                console.print(f"  Milestones: [bold]{len(data.get('milestones', []))}[/] steps recorded.")
                return
            else:
                console.print(f"[red]Server returned error: {resp.text}[/]")
        except Exception as e:
            console.print(f"[yellow]Server communication issue ({e}), falling back to direct storage...[/]")

    # Fallback to direct storage
    storage = TrackerStorage()
    tracker = ShipmentTracker()
    shipment = storage.add_shipment(clean_id, label, is_simulated=simulate)
    try:
        details = tracker.track(clean_id, force_simulated=simulate)
        storage.update_shipment_details(details)
        console.print(f"[bold green]✓ Added and queried package {clean_id}![/]")
        render_shipment_details(details, label)
    except Exception as e:
        console.print(f"[yellow]Package saved, but initial live check encountered: {e}[/]")

@cli.command("list")
def list_shipments():
    """List all tracked Ekart shipments."""
    status = get_server_status_api()
    console.print(render_banner(status))

    storage = TrackerStorage()
    shipments = storage.list_shipments(active_only=False)
    console.print(render_shipments_table(shipments))
    console.print()

@cli.command("info")
@click.argument("tracking_id")
def shipment_info(tracking_id: str):
    """View detailed milestone timeline and metadata for a tracked shipment."""
    clean_id = tracking_id.strip().upper()
    storage = TrackerStorage()
    shipment = storage.get_shipment(clean_id)
    if not shipment:
        console.print(f"[bold red]Shipment {clean_id} is not in tracking database.[/]")
        console.print(f"Use '[cyan]ekart-tracker add {clean_id}[/]' or '[cyan]ekart-tracker check {clean_id}[/]'.")
        return

    details = ShipmentDetails(
        tracking_id=shipment.tracking_id,
        status=shipment.current_status,
        expected_delivery_date=shipment.expected_delivery,
        is_delivered=shipment.is_delivered,
        fa_shipment=True,
        reached_nearest_hub="Hub" in shipment.current_status,
        milestones=shipment.milestones
    )
    render_shipment_details(details, shipment.label)

@cli.command("check")
@click.argument("tracking_id")
def check_live(tracking_id: str):
    """Directly query the live Ekart logistics portal for real-time status."""
    clean_id = tracking_id.strip().upper()
    console.print(f"[bold cyan]Querying live Ekart logistics network for [white]{clean_id}[/]...[/]")

    tracker = ShipmentTracker()
    try:
        details = tracker.track(clean_id)
        console.print(f"[bold green]✓ Live query successful![/]\n")
        render_shipment_details(details)
    except EkartTrackingError as e:
        console.print(f"[bold red]Ekart Tracking Error:[/] {e}")
    except Exception as e:
        console.print(f"[bold red]Error querying live tracker:[/] {e}")

@cli.command("refresh")
@click.argument("tracking_id")
def refresh_shipment(tracking_id: str):
    """Force an immediate refresh check and trigger notifications if changed."""
    clean_id = tracking_id.strip().upper()
    status = get_server_status_api()
    if status:
        try:
            resp = requests.post(f"{SERVER_BASE_URL}/api/shipments/{clean_id}/refresh", timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                sh = data.get("shipment", {})
                console.print(f"[bold green]✓ Refreshed {clean_id}:[/] Status is [bold cyan]{sh.get('current_status')}[/]")
                if data.get("status_changed"):
                    console.print("[bold yellow]🔔 Status change detected! Dispatched to both Email and Webhook channels.[/]")
                return
            else:
                console.print(f"[red]Server error: {resp.text}[/]")
        except Exception as e:
            console.print(f"[yellow]Could not reach server ({e}). Running local refresh...[/]")

    # Local fallback
    storage = TrackerStorage()
    shipment = storage.get_shipment(clean_id)
    if not shipment:
        console.print(f"[red]Shipment {clean_id} not found in database.[/]")
        return

    tracker = ShipmentTracker()
    notifier = DualNotificationManager(storage=storage)
    old_status = shipment.current_status
    details = tracker.track(clean_id, force_simulated=shipment.is_simulated)
    storage.update_shipment_details(details)
    console.print(f"[bold green]✓ Updated status: [white]{details.status}[/][/]")
    if details.status != old_status:
        console.print(f"[bold yellow]🔔 Status changed from '{old_status}' to '{details.status}'! Notifying both channels...[/]")
        notifier.notify_status_change(details, old_status)

@cli.command("simulate")
@click.argument("tracking_id")
def simulate_advance(tracking_id: str):
    """Advance a simulated package to its next milestone to test notifications."""
    clean_id = tracking_id.strip().upper()
    status = get_server_status_api()
    if status:
        try:
            resp = requests.post(f"{SERVER_BASE_URL}/api/shipments/{clean_id}/simulate", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                sh = data.get("shipment", {})
                console.print(f"[bold green]✓ Advanced simulated package {clean_id} to stage {data.get('stage')}:[/] [bold cyan]{sh.get('current_status')}[/]")
                console.print("[bold yellow]🔔 Dual notifications (Email & Webhook) dispatched![/]")
                return
            else:
                console.print(f"[red]Server error: {resp.text}[/]")
                return
        except Exception as e:
            console.print(f"[yellow]Could not connect to server ({e}). Running locally...[/]")

    # Local fallback
    storage = TrackerStorage()
    shipment = storage.get_shipment(clean_id)
    if not shipment:
        # Auto-create as simulated
        shipment = storage.add_shipment(clean_id, "Simulated Package", is_simulated=True)

    tracker = ShipmentTracker()
    notifier = DualNotificationManager(storage=storage)
    old_status = shipment.current_status
    tracker.mock_client.set_stage_from_status(clean_id, old_status)
    new_stage = tracker.mock_client.advance_stage(clean_id)
    details = tracker.mock_client.track(clean_id)
    storage.update_shipment_details(details)

    console.print(f"[bold green]✓ Simulated stage {new_stage}: [bold cyan]{details.status}[/][/]")
    if details.status != old_status:
        console.print(f"[bold yellow]🔔 Status changed from '{old_status}' to '{details.status}'. Dispatching dual notifications...[/]")
        results = notifier.notify_status_change(details, old_status)
        for ch, (ok, msg) in results.items():
            console.print(f"   • {ch.upper()}: {'[green]Success[/]' if ok else '[red]Failed[/]'} ({msg})")

@cli.command("remove")
@click.argument("tracking_id")
def remove_shipment(tracking_id: str):
    """Stop tracking and remove a shipment."""
    clean_id = tracking_id.strip().upper()
    status = get_server_status_api()
    if status:
        try:
            resp = requests.delete(f"{SERVER_BASE_URL}/api/shipments/{clean_id}", timeout=10)
            if resp.status_code == 200:
                console.print(f"[bold green]✓ Removed {clean_id} from tracking list.[/]")
                return
        except Exception:
            pass

    storage = TrackerStorage()
    if storage.remove_shipment(clean_id):
        console.print(f"[bold green]✓ Removed {clean_id} from tracking list.[/]")
    else:
        console.print(f"[yellow]Shipment {clean_id} not found.[/]")

@cli.command("notify-test")
@click.option("--id", default="TEST_FMPC999888", help="Tracking ID to test")
def notify_test(id: str):
    """Trigger test notifications to both Email and Webhook channels."""
    console.print(f"[bold cyan]Triggering dual-channel test notification for [white]{id}[/]...[/]")
    notifier = DualNotificationManager(storage=TrackerStorage())
    results = notifier.send_test_notifications(tracking_id=id)

    console.print("\n[bold]Notification Dispatch Results:[/]")
    for channel, (ok, msg) in results.items():
        status_label = "[bold green]✓ SUCCESS[/]" if ok else "[bold red]✗ FAILED[/]"
        console.print(f"  • [bold white]{channel.upper()}:[/] {status_label} - {msg}")
    console.print()

@cli.command("notifications")
@click.option("--limit", "-n", default=20, help="Number of notification logs to display")
@click.option("--id", default=None, help="Filter by tracking ID")
def list_notifications(limit: int, id: Optional[str]):
    """View recent dual-channel notification dispatch records."""
    storage = TrackerStorage()
    records = storage.list_notifications(tracking_id=id, limit=limit)
    console.print(render_notifications_table(records))
    console.print()

@cli.command("dashboard")
@click.option("--interval", "-i", default=3, help="Refresh interval in seconds")
def dashboard(interval: int):
    """Interactive live terminal dashboard (auto-refreshing monitor)."""
    console.clear()
    storage = TrackerStorage()

    console.print("[dim]Press Ctrl+C to exit dashboard mode...[/]")
    try:
        while True:
            console.clear()
            status = get_server_status_api()
            console.print(render_banner(status))
            
            shipments = storage.list_shipments(active_only=False)
            console.print(render_shipments_table(shipments))
            
            notifications = storage.list_notifications(limit=5)
            console.print(render_notifications_table(notifications))

            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Exited live dashboard.[/]")

@cli.command("menu")
def interactive_menu():
    """Interactive terminal navigation menu."""
    while True:
        status = get_server_status_api()
        console.clear()
        console.print(render_banner(status))
        console.print("[bold cyan]Interactive Terminal Menu:[/]")
        console.print("  [bold white]1.[/] List tracked shipments")
        console.print("  [bold white]2.[/] Add shipment to track")
        console.print("  [bold white]3.[/] View shipment milestone timeline")
        console.print("  [bold white]4.[/] Query live Ekart portal")
        console.print("  [bold white]5.[/] Advance simulated milestone (test alerts)")
        console.print("  [bold white]6.[/] View notification history (both channels)")
        console.print("  [bold white]7.[/] Send test alert to both channels")
        console.print("  [bold white]8.[/] Server daemon controls (start/stop/status)")
        console.print("  [bold white]9.[/] Live Watch Dashboard")
        console.print("  [bold white]0.[/] Exit")

        choice = click.prompt("\nEnter choice", default="1", type=str)
        if choice == "1":
            storage = TrackerStorage()
            console.print(render_shipments_table(storage.list_shipments(active_only=False)))
            click.pause()
        elif choice == "2":
            tid = click.prompt("Enter Ekart Tracking ID (e.g. FMPC... or SIM-1001)")
            lbl = click.prompt("Enter friendly label", default="Order")
            sim = click.confirm("Simulate this package?", default=tid.startswith("SIM-"))
            add_shipment.callback(tid, lbl, sim) # type: ignore
            click.pause()
        elif choice == "3":
            tid = click.prompt("Enter Tracking ID")
            shipment_info.callback(tid) # type: ignore
            click.pause()
        elif choice == "4":
            tid = click.prompt("Enter Ekart Tracking ID to check live")
            check_live.callback(tid) # type: ignore
            click.pause()
        elif choice == "5":
            tid = click.prompt("Enter simulated Tracking ID to advance", default="SIM-DEMO01")
            simulate_advance.callback(tid) # type: ignore
            click.pause()
        elif choice == "6":
            list_notifications.callback(20, None) # type: ignore
            click.pause()
        elif choice == "7":
            notify_test.callback("TEST_FMPC999888") # type: ignore
            click.pause()
        elif choice == "8":
            server_status.callback() # type: ignore
            sub_choice = click.prompt("Server command (start/stop/back)", default="back")
            if sub_choice == "start":
                server_start.callback(daemon=True) # type: ignore
            elif sub_choice == "stop":
                server_stop.callback() # type: ignore
            click.pause()
        elif choice == "9":
            dashboard.callback(interval=3) # type: ignore
        elif choice == "0":
            console.print("[green]Goodbye![/]")
            break

if __name__ == "__main__":
    cli()
