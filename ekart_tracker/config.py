import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Automatically load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"

@dataclass
class TrackerConfig:
    # Server
    host: str = field(default_factory=lambda: os.getenv("SERVER_HOST", "0.0.0.0" if os.getenv("RENDER") or os.getenv("PORT") else "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", os.getenv("SERVER_PORT", "5050"))))
    poll_interval: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "120")))
    
    # Notifications: Both channels
    email_enabled: bool = field(default_factory=lambda: os.getenv("NOTIFY_EMAIL_ENABLED", "true").lower() in ("true", "1", "yes"))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_use_tls: bool = field(default_factory=lambda: os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes"))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    email_from: str = field(default_factory=lambda: os.getenv("EMAIL_FROM", "Ekart Tracker <notifications@ekarttracker.local>"))
    email_to: str = field(default_factory=lambda: os.getenv("EMAIL_TO", ""))
    
    # Notification Channel 2: Discord (Bot & Webhook)
    webhook_enabled: bool = field(default_factory=lambda: os.getenv("NOTIFY_WEBHOOK_ENABLED", "true").lower() in ("true", "1", "yes"))
    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))
    
    # Discord Bot Settings
    discord_bot_enabled: bool = field(default_factory=lambda: os.getenv("DISCORD_BOT_ENABLED", "true").lower() in ("true", "1", "yes"))
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    discord_user_id: str = field(default_factory=lambda: os.getenv("DISCORD_USER_ID", ""))
    discord_guild_id: str = field(default_factory=lambda: os.getenv("DISCORD_GUILD_ID", ""))
    discord_prefix: str = field(default_factory=lambda: os.getenv("DISCORD_PREFIX", "!"))

    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    
    # Storage
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("STORAGE_DIR", str(DEFAULT_DATA_DIR))))
    
    @property
    def db_path(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "tracker.db"

    @property
    def pid_file(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / "server.pid"

config = TrackerConfig()
