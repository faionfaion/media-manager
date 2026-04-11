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

# Management chat IDs (group or private chats where the bot listens)
# Populated dynamically via /register command from authorized editors
MANAGEMENT_CHATS_FILE = ROOT / "config" / "management_chats.json"


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
        tg_bot_token="8585090528:AAHWmjiT9TIlmdtz0x8Q_YpUCnP3APEx7i8",
        tg_channel_id="-1002599675498",
        tg_channel_username="neromedia_uk",
        site_url="https://neromedia.faion.net",
        lang=["ua", "en", "pt", "es"],
        pipeline_modes=["generate", "digest"],
        cron_generate="0 7-19 * * *",  # hourly 7am-7pm UTC
        cron_publish="",  # inline with generate
        cron_digest="0 20 * * *",
    ),
    "longlife": MediaConfig(
        name="LongLife",
        slug="longlife",
        project_dir=PROJECTS_DIR / "longlife-faion-net",
        tg_bot_token="8585090528:AAHWmjiT9TIlmdtz0x8Q_YpUCnP3APEx7i8",
        tg_channel_id="-1003845412300",
        tg_channel_username="long_life_media",
        site_url="https://longlife.faion.net",
        lang="ua",
        cron_generate="0 7 * * *",
        cron_publish="5 9,12,15,18 * * *",
        cron_digest="5 20 * * *",
    ),
    "pashtelka": MediaConfig(
        name="Pashtelka",
        slug="pashtelka",
        project_dir=PROJECTS_DIR / "pashtelka-faion-net",
        tg_bot_token="8585090528:AAHWmjiT9TIlmdtz0x8Q_YpUCnP3APEx7i8",
        tg_channel_id="-1003726391778",
        tg_channel_username="pashtelka_news",
        site_url="https://pastelka.news",
        lang="ua",
        cron_generate="0 6 * * *",
        cron_publish="5 8,11,14,17 * * *",
        cron_digest="5 19 * * *",
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
