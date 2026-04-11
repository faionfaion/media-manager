"""Rate limiting for bot commands."""

from __future__ import annotations

import time
from collections import defaultdict

from config.settings import AGENT_RATE_LIMIT_PER_HOUR, MAX_COMMANDS_PER_MINUTE

# user_id -> list of timestamps
_command_history: dict[int, list[float]] = defaultdict(list)
_agent_history: dict[int, list[float]] = defaultdict(list)


def check_rate_limit(user_id: int) -> bool:
    """Check if user is within rate limits. Returns True if allowed."""
    now = time.time()
    window = 60.0  # 1 minute

    # Clean old entries
    _command_history[user_id] = [
        ts for ts in _command_history[user_id] if now - ts < window
    ]

    if len(_command_history[user_id]) >= MAX_COMMANDS_PER_MINUTE:
        return False

    _command_history[user_id].append(now)
    return True


def get_remaining_quota(user_id: int) -> int:
    """Return how many commands the user can still send this minute."""
    now = time.time()
    recent = [ts for ts in _command_history.get(user_id, []) if now - ts < 60.0]
    return max(0, MAX_COMMANDS_PER_MINUTE - len(recent))


def check_agent_rate_limit(user_id: int) -> bool:
    """Separate rate limit for expensive agent SDK calls (per hour)."""
    now = time.time()
    window = 3600.0  # 1 hour

    _agent_history[user_id] = [
        ts for ts in _agent_history[user_id] if now - ts < window
    ]

    if len(_agent_history[user_id]) >= AGENT_RATE_LIMIT_PER_HOUR:
        return False

    _agent_history[user_id].append(now)
    return True


def get_agent_remaining(user_id: int) -> int:
    """Return remaining agent calls this hour."""
    now = time.time()
    recent = [ts for ts in _agent_history.get(user_id, []) if now - ts < 3600.0]
    return max(0, AGENT_RATE_LIMIT_PER_HOUR - len(recent))
