"""Media Manager — main entry point.

Usage:
    python main.py serve          # Start FastAPI server + bot webhook
    python main.py setup-webhook  # Register Telegram webhook
    python main.py process-queue  # Process command queue once
    python main.py scheduler      # Run scheduled tasks (called by cron)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import API_HOST, API_PORT, LOG_DIR, MANAGER_BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "media-manager.log"),
    ],
)
logger = logging.getLogger(__name__)


def cmd_serve():
    """Start the FastAPI server."""
    import uvicorn
    from app.api.routes import app  # noqa: F811

    logger.info("Starting Media Manager on %s:%d", API_HOST, API_PORT)
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


def cmd_setup_webhook():
    """Register Telegram webhook for management bot."""
    import httpx

    # Webhook URL — the server must be publicly accessible
    webhook_url = f"https://media-manager.faion.net/webhook/telegram"
    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/setWebhook"

    resp = httpx.post(url, json={
        "url": webhook_url,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    })

    result = resp.json()
    if result.get("ok"):
        logger.info("Webhook set: %s", webhook_url)
        print(f"Webhook registered: {webhook_url}")
    else:
        logger.error("Webhook failed: %s", result)
        print(f"Error: {result}")
        sys.exit(1)


def cmd_remove_webhook():
    """Remove Telegram webhook (switch to polling)."""
    import httpx

    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/deleteWebhook"
    resp = httpx.post(url)
    print(f"Webhook removed: {resp.json()}")


def cmd_poll():
    """Run bot in polling mode (for development)."""
    import httpx
    import time

    from app.bot.handlers import handle_update
    from app.security.auth import load_management_chats

    load_management_chats()

    # Remove webhook first
    cmd_remove_webhook()

    logger.info("Starting polling mode...")
    offset = 0

    while True:
        try:
            url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/getUpdates"
            resp = httpx.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            updates = resp.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                response = handle_update(update)

                if response and response.get("method") == "sendMessage":
                    send_url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
                    payload = {
                        "chat_id": response["chat_id"],
                        "text": response["text"],
                        "parse_mode": response.get("parse_mode", "HTML"),
                        "disable_web_page_preview": True,
                    }
                    if "reply_markup" in response:
                        payload["reply_markup"] = json.dumps(response["reply_markup"])
                    httpx.post(send_url, json=payload)

        except KeyboardInterrupt:
            logger.info("Polling stopped")
            break
        except Exception as e:
            logger.error("Polling error: %s", e)
            time.sleep(5)


def cmd_process_queue():
    """Process pending command queue."""
    from app.orchestrator.runner import process_queue
    from app.security.auth import load_management_chats

    load_management_chats()
    count = process_queue()
    print(f"Processed {count} commands")


def cmd_scheduler():
    """Run scheduled pipeline tasks."""
    from app.orchestrator.runner import run_scheduled
    from app.security.auth import load_management_chats

    load_management_chats()
    run_scheduled()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    commands = {
        "serve": cmd_serve,
        "setup-webhook": cmd_setup_webhook,
        "remove-webhook": cmd_remove_webhook,
        "poll": cmd_poll,
        "process-queue": cmd_process_queue,
        "scheduler": cmd_scheduler,
    }

    cmd = sys.argv[1]
    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands)}")
        sys.exit(1)
