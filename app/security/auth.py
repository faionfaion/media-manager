"""Authentication and authorization for editor commands.

Two checks, AND-combined:
  1. user_id in AUTHORIZED_EDITORS  (settings.py)
  2. chat_id in ALLOWED_CHATS       (settings.py preset + env override)

No dynamic /register — chat allowlist is static. Adding a chat requires
setting MEDIA_MANAGER_ALLOWED_CHATS env and restarting the bot.
"""

from __future__ import annotations

import json
import logging

from config.settings import ALLOWED_CHATS, AUTHORIZED_EDITORS, MANAGEMENT_CHATS_FILE

logger = logging.getLogger(__name__)

# In-memory cache of allowed chats (ALLOWED_CHATS preset + optional legacy file)
_management_chats: set[int] = set()


def load_management_chats() -> None:
    """Load allowed chats from settings (preset + env) merged with legacy file."""
    global _management_chats
    chats: set[int] = set(ALLOWED_CHATS)
    if MANAGEMENT_CHATS_FILE.exists():
        try:
            data = json.loads(MANAGEMENT_CHATS_FILE.read_text(encoding="utf-8"))
            file_chats = set(int(c) for c in data.get("chat_ids", []))
            chats.update(file_chats)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    _management_chats = chats
    logger.info(
        "Loaded %d allowed chats (preset: %d, file: %d)",
        len(_management_chats),
        len(ALLOWED_CHATS),
        len(_management_chats) - len(ALLOWED_CHATS),
    )


def is_authorized(user_id: int) -> bool:
    """Check if a Telegram user is an authorized editor."""
    return user_id in AUTHORIZED_EDITORS


def is_management_chat(chat_id: int) -> bool:
    """Check if a chat is on the static allowlist."""
    return chat_id in _management_chats


def get_management_chats() -> set[int]:
    """Return current allowed chat IDs."""
    return _management_chats.copy()
