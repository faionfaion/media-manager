"""Telegram Mini App authentication via initData HMAC-SHA256 validation.

Adapted from nero-channel-web/services/auth_service.py.
Telegram sends URL-encoded initData with user info + HMAC signature.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, unquote

from config.settings import AUTHORIZED_EDITORS, MANAGER_BOT_TOKEN


def validate_telegram_init_data(
    init_data: str,
    bot_token: str | None = None,
    max_age_seconds: int = 3600,
) -> dict:
    """Validate Telegram Mini App initData and return parsed user data.

    Args:
        init_data: URL-encoded string from Telegram WebApp
        bot_token: Bot token for HMAC verification (defaults to MANAGER_BOT_TOKEN)
        max_age_seconds: Max allowed age of auth_date (default 1 hour)

    Returns:
        dict with 'user' (parsed JSON), 'auth_date' (int), etc.

    Raises:
        ValueError: If signature invalid, data expired, or user not authorized
    """
    if not init_data:
        raise ValueError("Empty init data")

    token = bot_token or MANAGER_BOT_TOKEN
    if not token:
        raise ValueError("Bot token not configured")

    params = parse_qs(init_data, keep_blank_values=True)

    if "hash" not in params:
        raise ValueError("Missing hash in init data")

    received_hash = params.pop("hash")[0]

    # HMAC key: SHA-256("WebAppData", bot_token)
    key = hmac.new(
        b"WebAppData",
        msg=token.encode(),
        digestmod=hashlib.sha256,
    ).digest()

    # Data string: sorted key=value pairs joined by newlines
    check_pairs = sorted(f"{k}={v[0]}" for k, v in params.items())
    check_string = "\n".join(check_pairs)

    computed_hash = hmac.new(
        key,
        msg=check_string.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise ValueError("Invalid Telegram signature")

    # Parse fields
    result: dict = {}
    for k, v_list in params.items():
        v = v_list[0]
        if k == "user":
            try:
                result[k] = json.loads(v)
            except json.JSONDecodeError:
                result[k] = json.loads(unquote(v))
        elif k == "auth_date":
            result[k] = int(v)
        else:
            result[k] = v

    if "user" not in result:
        raise ValueError("Missing user in init data")

    # Check auth_date freshness (prevent replay attacks)
    auth_date = result.get("auth_date", 0)
    if time.time() - auth_date > max_age_seconds:
        raise ValueError(f"Init data expired (older than {max_age_seconds}s)")

    # Check user authorization
    user_id = result["user"].get("id", 0)
    if user_id not in AUTHORIZED_EDITORS:
        raise ValueError(f"User {user_id} not authorized")

    return result
