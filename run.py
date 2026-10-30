import sys
import signal
import threading
import asyncio
import logging

from ekart_tracker.config import config
from ekart_tracker.server import TrackingServerDaemon
from ekart_tracker.bot import setup_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [app_runner]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("app_runner")

def start_discord_bot_thread():
    """Runs the Discord Bot in an independent asyncio event loop."""
    if not config.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN not configured. Discord Bot disabled.")
        return

    logger.info("Initializing Discord Bot...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot = setup_bot()

    try:
        loop.run_until_complete(bot.start(config.discord_bot_token))
    except Exception as e:
        logger.error("Discord Bot encountered an error: %s", e)
    finally:
        loop.close()

def main():
    logger.info("Starting Ekart Tracker Application on Host=%s, Port=%d", config.host, config.port)

    # 1. Start Discord Bot in background thread if token configured
    if config.discord_bot_token:
        bot_thread = threading.Thread(target=start_discord_bot_thread, daemon=True, name="DiscordBotThread")
        bot_thread.start()
        logger.info("Discord Bot background thread started.")
    else:
        logger.info("Running in Server-only mode (set DISCORD_BOT_TOKEN in Render environment to enable the bot).")

    # 2. Start the Server Daemon & Background Polling Worker
    server = TrackingServerDaemon(host=config.host, port=config.port)

    def handle_sigterm(signum, frame):
        logger.info("Received termination signal (%s), shutting down...", signum)
        server.stop()
        sys.exit(0)

    try:
        signal.signal(signal.SIGTERM, handle_sigterm)
        signal.signal(signal.SIGINT, handle_sigterm)
    except ValueError:
        pass

    server.start()

if __name__ == "__main__":
    main()
