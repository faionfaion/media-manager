"""Central configuration for Media Manager."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = Path.home() / "workspace" / "projects"

# Management bot (separate from publishing bots)
# Token loaded from ~/workspace/.env or environment
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN", "")

# Authorized editor Telegram user IDs (only these can send commands)
AUTHORIZED_EDITORS: set[int] = {
    267619672,  # Ruslan (primary)
}


def _load_allowed_chats() -> set[int]:
    """Static allowlist of chat IDs where the bot will respond.

    Source: hardcoded preset (Ruslan's DM) + env override
    MEDIA_MANAGER_ALLOWED_CHATS (comma-separated ints, e.g. "-100123,-100456").
    Both AUTHORIZED_EDITORS and ALLOWED_CHATS must match — chat allowlist is
    AND-ed with user allowlist; no dynamic /register.
    """
    chats: set[int] = {267619672}  # Ruslan's DM (user_id == chat_id for private)
    extra = os.getenv("MEDIA_MANAGER_ALLOWED_CHATS", "").strip()
    if extra:
        for token in extra.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                chats.add(int(token))
            except ValueError:
                pass
    return chats


# Static chat allowlist — to add a chat: set MEDIA_MANAGER_ALLOWED_CHATS env and restart.
ALLOWED_CHATS: set[int] = _load_allowed_chats()

# Legacy file kept for backward compat; merged into allowlist on load but no
# longer written to. Dynamic /register is disabled.
MANAGEMENT_CHATS_FILE = ROOT / "config" / "management_chats.json"


# Per-user media access — controls which outlets a user sees in the Mini App
# and which can trigger actions. Sentinel "*" means all outlets.
# Keys are Telegram user IDs (must also be in AUTHORIZED_EDITORS for any access).
USER_MEDIA_ACCESS: dict[int, set[str] | str] = {
    267619672: "*",  # Ruslan — full access
}


def get_allowed_media(user_id: int) -> set[str]:
    """Return the set of media slugs the user is allowed to see/control.

    Returns empty set if the user is not in USER_MEDIA_ACCESS — combined with
    the AUTHORIZED_EDITORS check this means no access. Resolves the "*" sentinel
    to the full set of configured outlets.
    """
    entry = USER_MEDIA_ACCESS.get(user_id)
    if entry is None:
        return set()
    if entry == "*":
        return set(MEDIA_OUTLETS.keys())
    return set(entry)


@dataclass
class MediaConfig:
    """Per-media-outlet configuration."""

    name: str
    slug: str  # neromedia, longlife, pashtelka
    project_dir: Path
    tg_bot_token: str
    tg_channel_id: str
    tg_channel_username: str
    site_url: str
    lang: str | list[str]
    pipeline_modes: list[str] = field(default_factory=lambda: ["generate", "publish", "digest"])
    cron_generate: str = "0 7 * * *"
    cron_publish: str = "5 9,12,15,18 * * *"
    cron_digest: str = "5 20 * * *"


# All managed media outlets
MEDIA_OUTLETS: dict[str, MediaConfig] = {
    "neromedia": MediaConfig(
        name="NeroMedia",
        slug="neromedia",
        project_dir=PROJECTS_DIR / "neromedia-faion-net",
        tg_bot_token="8578996384:AAFhkTHh_D40VdCc7em5U9taM5a-o00JzaA",
        tg_channel_id="-1002599675498",
        tg_channel_username="neromedia_uk",
        site_url="https://neromedia.faion.net",
        lang=["ua", "en", "pt", "es"],
        pipeline_modes=["generate", "publish", "digest"],
        # 3 generate slots/day at 09:17, 13:17, 17:17 UTC — matches plan.json SLOTS in
        # neromedia-faion-net/scripts/manage_state.py (guide, material, guide).
        cron_generate="17 9,13,17 * * *",
        # Publish ~1h after each generate slot: 10:47, 14:47, 18:47 UTC — picks oldest unpublished
        cron_publish="47 10,14,18 * * *",
        cron_digest="13 20 * * *",
    ),
    "longlife": MediaConfig(
        name="LongLife",
        slug="longlife",
        project_dir=PROJECTS_DIR / "longlife-faion-net",
        tg_bot_token="8578996384:AAFhkTHh_D40VdCc7em5U9taM5a-o00JzaA",
        tg_channel_id="-1003845412300",
        tg_channel_username="long_life_media",
        site_url="https://longlife.faion.net",
        lang="ua",
        cron_generate="3 3 * * *",  # 03:03 UTC (spread across night)
        cron_publish="5 9,12,15,18 * * *",
        cron_digest="43 20 * * *",
    ),
    "pashtelka": MediaConfig(
        name="Pashtelka",
        slug="pashtelka",
        project_dir=PROJECTS_DIR / "pashtelka-faion-net",
        tg_bot_token="8578996384:AAFhkTHh_D40VdCc7em5U9taM5a-o00JzaA",
        tg_channel_id="-1003726391778",
        tg_channel_username="pashtelka_news",
        site_url="https://pastelka.news",
        lang="ua",
        cron_generate="17 1 * * *",  # 01:17 UTC (spread across night)
        cron_publish="",  # DISABLED 2026-04-24: digest-only model, no per-slot TG publishes
        cron_digest="0 20 * * *",  # 20:00 UTC = 21:00 Lisbon (WEST, April)
    ),
    "ender": MediaConfig(
        name="Ender",
        slug="ender",
        project_dir=PROJECTS_DIR / "ender-faion-net",
        tg_bot_token="8578996384:AAFhkTHh_D40VdCc7em5U9taM5a-o00JzaA",
        tg_channel_id="-1003353271043",
        tg_channel_username="ender_faion_ua",
        site_url="https://ender.faion.net",
        lang=["ua", "en"],
        cron_generate="47 4 * * *",  # 04:47 UTC (spread across night)
        cron_publish="5 9,11,14,17 * * *",
        cron_digest="23 19 * * *",
    ),
}

# API settings
API_HOST = "0.0.0.0"
API_PORT = 8900
API_SECRET = os.getenv("MEDIA_MANAGER_SECRET", "change-me-in-production")

# Security
MAX_MESSAGE_LENGTH = 2000  # max chars from editor messages
MAX_COMMANDS_PER_MINUTE = 10  # rate limit per user
PROMPT_INJECTION_PATTERNS_FILE = ROOT / "config" / "injection_patterns.json"

# Agent SDK config
AGENT_MODEL = os.getenv("AGENT_MODEL", "opus")
AGENT_TIMEOUT = 120  # seconds per agent call
AGENT_RATE_LIMIT_PER_HOUR = 20  # max agent calls per hour (cost control)
AGENT_RETRY_MAX = 3
AGENT_RETRY_BASE_DELAY = 5.0
AGENT_RETRY_MAX_DELAY = 60.0

# Allowed pipeline dirs for agent tools (sandbox)
AGENT_ALLOWED_DIRS = [str(cfg.project_dir) for cfg in MEDIA_OUTLETS.values()] + [str(ROOT)]

# Logging
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
