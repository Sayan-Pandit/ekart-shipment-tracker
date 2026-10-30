import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Automatically load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"

@dataclass
class TrackerConfig:
    # Server settings
    host: str = field(default_factory=lambda: os.getenv("SERVER_HOST", "0.0.0.0" if os.getenv("RENDER") or os.getenv("PORT") else "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", os.getenv("SERVER_PORT", "5050"))))
    poll_interval: int = field(default_factory=lambda: max(15, int(os.getenv("POLL_INTERVAL_SECONDS", "120"))))
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "30")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    
    # Notifications: Channel 1 (Email via SMTP)
    email_enabled: bool = field(default_factory=lambda: os.getenv("NOTIFY_EMAIL_ENABLED", "true").lower() in ("true", "1", "yes"))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_use_tls: bool = field(default_factory=lambda: os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", "Ekart Tracker <notifications@ekarttracker.local>"))
    email_to: str = field(default_factory=lambda: os.getenv("EMAIL_TO", ""))
    
    # Notifications: Channel 2 (Discord Bot & Webhook)
    webhook_enabled: bool = field(default_factory=lambda: os.getenv("NOTIFY_WEBHOOK_ENABLED", "true").lower() in ("true", "1", "yes"))
    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))
    
    # Discord Bot Settings
    discord_bot_enabled: bool = field(default_factory=lambda: os.getenv("DISCORD_BOT_ENABLED", "true").lower() in ("true", "1", "yes"))
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    discord_user_id: str = field(default_factory=lambda: os.getenv("DISCORD_USER_ID", ""))
    discord_guild_id: str = field(default_factory=lambda: os.getenv("DISCORD_GUILD_ID", ""))
    discord_prefix: str = field(default_factory=lambda: os.getenv("DISCORD_PREFIX", "!"))

    # Telegram Bot Settings (Optional fallback)
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    
    # Storage & Database
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("STORAGE_DIR", str(DEFAULT_DATA_DIR))))
    
    # Timezone settings (Default: Asia/Kolkata / IST - Indian Standard Time)
    timezone_name: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))
    
    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "tracker.db"

    @property
    def pid_file(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "server.pid"

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return configuration dictionary with sensitive credentials safely masked."""
        def mask(val: str, prefix_len: int = 4) -> str:
            if not val:
                return "<not-set>"
            if len(val) <= prefix_len:
                return "***"
            return f"{val[:prefix_len]}...***"

        return {
            "server": {
                "host": self.host,
                "port": self.port,
                "poll_interval_seconds": self.poll_interval,
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "log_level": self.log_level
            },
            "email": {
                "enabled": self.email_enabled,
                "smtp_host": self.smtp_host,
                "smtp_port": self.smtp_port,
                "smtp_user": mask(self.smtp_user, 3),
                "is_configured": bool(self.smtp_user and self.smtp_password and self.email_to)
            },
            "discord": {
                "bot_enabled": self.discord_bot_enabled,
                "bot_token": mask(self.discord_bot_token, 6),
                "channel_id": mask(self.discord_channel_id, 4),
                "user_id": mask(self.discord_user_id, 4),
                "prefix": self.discord_prefix,
                "webhook_configured": bool(self.webhook_url)
            },
            "database": {
                "engine": "PostgreSQL" if self.database_url else "SQLite",
                "is_cloud_postgres": bool(self.database_url)
            }
        }

config = TrackerConfig()

# Timezone resolution (Default: Indian Standard Time - Asia/Kolkata / UTC+05:30)
try:
    from zoneinfo import ZoneInfo
    APP_TIMEZONE = ZoneInfo(config.timezone_name)
except Exception:
    APP_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="IST")

def now_ist() -> datetime:
    """Return the current time in IST (Indian Standard Time)."""
    return datetime.now(APP_TIMEZONE)

def from_timestamp_ist(ts_ms: float) -> datetime:
    """Convert millisecond timestamp to IST datetime."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=APP_TIMEZONE)

def format_datetime_ist(dt: datetime, fmt: str = "%b %d, %Y %I:%M %p IST") -> str:
    """Format any datetime object into an IST string."""
    if dt.tzinfo is None:
        # Assume local/naive is already IST or localize it
        dt = dt.replace(tzinfo=APP_TIMEZONE)
    else:
        dt = dt.astimezone(APP_TIMEZONE)
    return dt.strftime(fmt)
