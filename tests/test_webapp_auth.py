"""Tests for Telegram Mini App authentication."""

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.webapp_auth import validate_telegram_init_data


def _make_init_data(user_id: int = 267619672, bot_token: str = "test:TOKEN", auth_date: int | None = None) -> str:
    """Create valid initData for testing."""
    if auth_date is None:
        auth_date = int(time.time())

    user = json.dumps({"id": user_id, "first_name": "Test", "username": "test"})
    pairs = {"auth_date": str(auth_date), "user": user}

    key = hmac.new(b"WebAppData", msg=bot_token.encode(), digestmod=hashlib.sha256).digest()
    check_string = "\n".join(sorted(f"{k}={v}" for k, v in pairs.items()))
    hash_val = hmac.new(key, msg=check_string.encode(), digestmod=hashlib.sha256).hexdigest()

    return f"auth_date={auth_date}&user={quote(user)}&hash={hash_val}"


class TestWebAppAuth:
    """Test Telegram Mini App authentication."""

    def test_valid_init_data(self):
        token = "test:TOKEN"
        data = _make_init_data(user_id=267619672, bot_token=token)
        result = validate_telegram_init_data(data, bot_token=token)
        assert result["user"]["id"] == 267619672
        assert "auth_date" in result

    def test_invalid_signature(self):
        token = "test:TOKEN"
        data = _make_init_data(bot_token=token)
        # Tamper with the hash
        data = data.replace("hash=", "hash=0000")
        try:
            validate_telegram_init_data(data, bot_token=token)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "signature" in str(e).lower() or "Invalid" in str(e)

    def test_expired_init_data(self):
        token = "test:TOKEN"
        old_time = int(time.time()) - 7200  # 2 hours ago
        data = _make_init_data(bot_token=token, auth_date=old_time)
        try:
            validate_telegram_init_data(data, bot_token=token, max_age_seconds=3600)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "expired" in str(e).lower()

    def test_unauthorized_user(self):
        token = "test:TOKEN"
        data = _make_init_data(user_id=99999, bot_token=token)
        try:
            validate_telegram_init_data(data, bot_token=token)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not authorized" in str(e).lower()

    def test_missing_hash(self):
        try:
            validate_telegram_init_data("auth_date=123&user={}", bot_token="test:TOKEN")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "hash" in str(e).lower()

    def test_empty_init_data(self):
        try:
            validate_telegram_init_data("", bot_token="test:TOKEN")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "empty" in str(e).lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
