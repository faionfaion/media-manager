"""Authentication and authorization for editor commands."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config.settings import AUTHORIZED_EDITORS, MANAGEMENT_CHATS_FILE

logger = logging.getLogger(__name__)

# In-memory cache of management chats (loaded from file)
_management_chats: set[int] = set()


def load_management_chats() -> None:
    """Load registered management chats from disk."""
    global _management_chats
    if MANAGEMENT_CHATS_FILE.exists():
        try:
            data = json.loads(MANAGEMENT_CHATS_FILE.read_text(encoding="utf-8"))
            _management_chats = set(data.get("chat_ids", []))
            logger.info("Loaded %d management chats", len(_management_chats))
        except (json.JSONDecodeError, KeyError):
            _management_chats = set()
    else:
        _management_chats = set()


def save_management_chats() -> None:
    """Persist management chats to disk."""
    MANAGEMENT_CHATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANAGEMENT_CHATS_FILE.write_text(
        json.dumps({"chat_ids": sorted(_management_chats)}, indent=2),
        encoding="utf-8",
    )


def register_chat(chat_id: int) -> bool:
    """Register a chat as management chat. Returns True if newly added."""
    if chat_id in _management_chats:
        return False
    _management_chats.add(chat_id)
    save_management_chats()
    logger.info("Registered management chat: %d", chat_id)
    return True


def unregister_chat(chat_id: int) -> bool:
    """Remove a chat from management chats."""
    if chat_id not in _management_chats:
        return False
    _management_chats.discard(chat_id)
    save_management_chats()
    return True


def is_authorized(user_id: int) -> bool:
    """Check if a Telegram user is an authorized editor."""
    return user_id in AUTHORIZED_EDITORS


def is_management_chat(chat_id: int) -> bool:
    """Check if a chat is a registered management chat."""
    return chat_id in _management_chats


def get_management_chats() -> set[int]:
    """Return current management chat IDs."""
    return _management_chats.copy()
