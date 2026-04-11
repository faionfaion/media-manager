"""Input validation for bot commands and callback data.

Prevents:
- Path traversal in slugs and file arguments
- Command injection via crafted arguments
- Oversized inputs that could cause DoS
- Malformed callback_data exploitation
"""

from __future__ import annotations

import re

# Allowed characters in media slugs, article slugs, commands
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
_CALLBACK_ACTION_RE = re.compile(r"^[a-z_]{1,30}$")
_SAFE_TEXT_RE = re.compile(r"^[\w\s.,!?;:'\"\-—–()@#%&*/+=\[\]{}<>₴€$£¥…\u0400-\u04FF\u00C0-\u024F]+$", re.UNICODE)

# Max lengths for various inputs
MAX_SLUG_LENGTH = 80
MAX_COMMAND_ARG_LENGTH = 200
MAX_NOTE_LENGTH = 2000
MAX_CALLBACK_DATA_LENGTH = 64


def validate_slug(value: str) -> str | None:
    """Validate and return a safe slug, or None if invalid.

    Prevents path traversal (../, /etc/), null bytes, and shell metacharacters.
    """
    if not value or len(value) > MAX_SLUG_LENGTH:
        return None
    # Reject if contains null bytes (indicates malicious input)
    if "\x00" in value:
        return None
    # Must match safe pattern
    if not _SLUG_RE.match(value):
        return None
    # Extra safety: no path components
    if ".." in value or "/" in value or "\\" in value:
        return None
    return value


def validate_media_slug(value: str, valid_slugs: set[str]) -> str | None:
    """Validate media slug against known outlets."""
    clean = validate_slug(value)
    if clean and clean in valid_slugs:
        return clean
    return None


def validate_callback_data(data: str) -> tuple[str, str, str] | None:
    """Parse and validate callback_data string.

    Expected format: "action:media" or "action:media:param" or "cancel".
    Returns (action, media, param) or None if invalid.
    """
    if not data or len(data) > MAX_CALLBACK_DATA_LENGTH:
        return None

    # Reject if contains null bytes
    if "\x00" in data:
        return None

    if data == "cancel":
        return ("cancel", "", "")

    parts = data.split(":", 2)
    if len(parts) < 2:
        return None

    action = parts[0]
    media = parts[1]
    param = parts[2] if len(parts) > 2 else ""

    # Validate action
    if not _CALLBACK_ACTION_RE.match(action):
        return None

    # Validate media (if present)
    if media and not _SLUG_RE.match(media):
        return None

    # Validate param (slug-like if present)
    if param and not _SLUG_RE.match(param):
        return None

    return (action, media, param)


def validate_command_args(args: list[str], max_args: int = 5) -> list[str]:
    """Sanitize command arguments.

    Removes null bytes, limits length, caps number of args.
    """
    safe_args = []
    for arg in args[:max_args]:
        # Remove null bytes and control characters
        clean = arg.replace("\x00", "")
        clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", clean)
        # Limit length
        if len(clean) > MAX_COMMAND_ARG_LENGTH:
            clean = clean[:MAX_COMMAND_ARG_LENGTH]
        if clean:
            safe_args.append(clean)
    return safe_args


def sanitize_note_text(text: str) -> str:
    """Sanitize editorial note text before saving to file.

    Prevents file injection and ensures safe Markdown content.
    """
    # Remove null bytes
    text = text.replace("\x00", "")
    # Remove control characters (keep newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # Limit length
    if len(text) > MAX_NOTE_LENGTH:
        text = text[:MAX_NOTE_LENGTH] + "... [truncated]"
    return text.strip()
