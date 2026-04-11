"""Pipeline orchestrator — executes queued commands and scheduled runs.

Processes command queue files from queue/ directory and runs pipelines
in the respective project directories.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from config.settings import MANAGER_BOT_TOKEN, MEDIA_OUTLETS

logger = logging.getLogger(__name__)

QUEUE_DIR = Path(__file__).resolve().parent.parent.parent / "queue"
DONE_DIR = QUEUE_DIR / "done"


def process_queue() -> int:
    """Process all pending commands in the queue. Returns count processed."""
    if not QUEUE_DIR.exists():
        return 0

    DONE_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0

    for cmd_file in sorted(QUEUE_DIR.glob("*.json")):
        try:
            cmd = json.loads(cmd_file.read_text(encoding="utf-8"))
            media_slug = cmd.get("media")
            command = cmd.get("command")

            if media_slug not in MEDIA_OUTLETS:
                logger.warning("Unknown media in queue: %s", media_slug)
                cmd_file.rename(DONE_DIR / cmd_file.name)
                continue

            cfg = MEDIA_OUTLETS[media_slug]
            logger.info("Executing: %s/%s", media_slug, command)

            success = _run_pipeline(cfg.project_dir, command, media_slug)

            # Move to done
            result = {**cmd, "success": success, "completed_at": datetime.now(timezone.utc).isoformat()}
            done_file = DONE_DIR / cmd_file.name
            done_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            cmd_file.unlink()
            processed += 1

            # Notify management chats
            status_emoji = "✅" if success else "❌"
            _notify_managers(
                f"{status_emoji} {cfg.name}: {command} {'completed' if success else 'failed'}"
            )

        except Exception as e:
            logger.error("Error processing %s: %s", cmd_file.name, e)
            # Move to done with error
            cmd_file.rename(DONE_DIR / cmd_file.name)
            processed += 1

    return processed


def _run_pipeline(project_dir: Path, mode: str, media_slug: str) -> bool:
    """Run a pipeline mode in the project directory."""
    cmd = ["python3", "-m", "pipeline", mode, "-v"]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            env=_get_env(project_dir),
        )

        if result.returncode == 0:
            logger.info("%s/%s completed successfully", media_slug, mode)
            return True
        else:
            logger.error(
                "%s/%s failed (exit %d): %s",
                media_slug, mode, result.returncode,
                result.stderr[-500:] if result.stderr else "no stderr",
            )
            return False

    except subprocess.TimeoutExpired:
        logger.error("%s/%s timed out after 600s", media_slug, mode)
        return False
    except Exception as e:
        logger.error("%s/%s error: %s", media_slug, mode, e)
        return False


def _get_env(project_dir: Path) -> dict:
    """Build environment for pipeline subprocess."""
    import os
    env = os.environ.copy()

    # Load .env from workspace if exists
    workspace_env = Path.home() / "workspace" / ".env"
    if workspace_env.exists():
        for line in workspace_env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")

    env["PYTHONPATH"] = str(project_dir)
    return env


def _notify_managers(text: str) -> None:
    """Send notification to all management chats."""
    from app.security.auth import get_management_chats

    import httpx

    chats = get_management_chats()
    if not chats:
        return

    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
    for chat_id in chats:
        try:
            httpx.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
        except Exception as e:
            logger.error("Failed to notify chat %d: %s", chat_id, e)


# Track last scheduled run to prevent double-fires within the same minute
_LAST_RUN_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / ".last_scheduled"


def _already_ran(slug: str, mode: str, hour: int, minute: int) -> bool:
    """Check if this exact schedule slot already ran (dedup within minute)."""
    key = f"{slug}:{mode}:{hour:02d}:{minute:02d}"
    if _LAST_RUN_FILE.exists():
        content = _LAST_RUN_FILE.read_text(encoding="utf-8").strip()
        return key in content.split("\n")
    return False


def _mark_ran(slug: str, mode: str, hour: int, minute: int) -> None:
    """Mark a schedule slot as executed."""
    key = f"{slug}:{mode}:{hour:02d}:{minute:02d}"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Reset file daily
    existing = ""
    if _LAST_RUN_FILE.exists():
        raw = _LAST_RUN_FILE.read_text(encoding="utf-8")
        if raw.startswith(today):
            existing = raw
    if not existing.startswith(today):
        existing = today + "\n"

    _LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _LAST_RUN_FILE.write_text(existing.rstrip() + "\n" + key + "\n", encoding="utf-8")


def run_scheduled() -> None:
    """Check and run scheduled pipeline tasks based on cron configs.

    Called every minute by cron. Uses dedup file to prevent double-fires.
    """
    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute

    for slug, cfg in MEDIA_OUTLETS.items():
        # Check generate schedule
        if cfg.cron_generate and _cron_matches(cfg.cron_generate, h, m):
            if not _already_ran(slug, "generate", h, m):
                logger.info("Scheduled generate for %s at %02d:%02d", slug, h, m)
                _mark_ran(slug, "generate", h, m)
                success = _run_pipeline(cfg.project_dir, "generate", slug)
                _notify_managers(
                    f"{'✅' if success else '❌'} <b>{cfg.name}</b>: scheduled generate "
                    f"{'completed' if success else 'failed'}"
                )

        # Check publish schedule
        if cfg.cron_publish and _cron_matches(cfg.cron_publish, h, m):
            if not _already_ran(slug, "publish", h, m):
                logger.info("Scheduled publish for %s at %02d:%02d", slug, h, m)
                _mark_ran(slug, "publish", h, m)
                _run_pipeline(cfg.project_dir, "publish", slug)

        # Check digest schedule
        if cfg.cron_digest and _cron_matches(cfg.cron_digest, h, m):
            if not _already_ran(slug, "digest", h, m):
                logger.info("Scheduled digest for %s at %02d:%02d", slug, h, m)
                _mark_ran(slug, "digest", h, m)
                _run_pipeline(cfg.project_dir, "digest", slug)


def _cron_matches(cron_expr: str, hour: int, minute: int) -> bool:
    """Simple cron matching for minute and hour fields only."""
    parts = cron_expr.split()
    if len(parts) < 2:
        return False

    cron_min, cron_hour = parts[0], parts[1]

    # Check minute
    if not _field_matches(cron_min, minute):
        return False

    # Check hour
    if not _field_matches(cron_hour, hour):
        return False

    return True


def _field_matches(field: str, value: int) -> bool:
    """Check if a cron field matches a value."""
    if field == "*":
        return True

    # Handle */N
    if field.startswith("*/"):
        step = int(field[2:])
        return value % step == 0

    # Handle comma-separated values
    for part in field.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            if int(start) <= value <= int(end):
                return True
        elif int(part) == value:
            return True

    return False
