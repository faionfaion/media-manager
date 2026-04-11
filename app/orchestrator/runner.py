"""Pipeline orchestrator — executes queued commands and scheduled runs.

Processes command queue files from queue/ directory and runs pipelines
in the respective project directories.
"""

from __future__ import annotations

import json
import logging
import os
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


# Timeouts per mode (seconds)
_MODE_TIMEOUTS = {
    "generate": 2400,  # 40 min — full pipeline: editorial plan, research, generate, review, deploy
    "publish": 120,    # 2 min — mechanical TG publish, no LLM
    "digest": 600,     # 10 min — compile + LLM summary
}

# Lock dir to prevent concurrent runs of the same pipeline
_LOCK_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _run_pipeline(project_dir: Path, mode: str, media_slug: str) -> bool:
    """Run a pipeline mode in the project directory.

    For 'generate' mode: runs as background process (too long for sync).
    For 'publish'/'digest': runs synchronously with appropriate timeout.
    """
    cmd = ["python3", "-m", "pipeline", mode, "-v"]
    timeout = _MODE_TIMEOUTS.get(mode, 600)

    # Prevent concurrent runs of same pipeline/mode
    lock_file = _LOCK_DIR / f".lock_{media_slug}_{mode}"
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            os.kill(pid, 0)  # check if alive (signal 0)
            logger.info("%s/%s already running (pid %d), skipping", media_slug, mode, pid)
            return True  # not an error, just skip
        except (ValueError, OSError):
            lock_file.unlink(missing_ok=True)  # stale lock

    if mode == "generate":
        # Run in background — generate is too long for synchronous execution
        return _run_pipeline_background(cmd, project_dir, media_slug, mode, lock_file)
    else:
        return _run_pipeline_sync(cmd, project_dir, media_slug, mode, timeout, lock_file)


def _run_pipeline_sync(
    cmd: list, project_dir: Path, media_slug: str, mode: str, timeout: int, lock_file: Path
) -> bool:
    """Run pipeline synchronously (for quick operations like publish/digest)."""
    try:
        lock_file.write_text(str(os.getpid()))
        result = subprocess.run(
            cmd, cwd=str(project_dir), capture_output=True, text=True,
            timeout=timeout, env=_get_env(project_dir),
        )
        lock_file.unlink(missing_ok=True)

        if result.returncode == 0:
            logger.info("%s/%s completed successfully", media_slug, mode)
            return True
        else:
            logger.error("%s/%s failed (exit %d): %s",
                         media_slug, mode, result.returncode,
                         result.stderr[-500:] if result.stderr else "no stderr")
            return False

    except subprocess.TimeoutExpired:
        lock_file.unlink(missing_ok=True)
        logger.error("%s/%s timed out after %ds", media_slug, mode, timeout)
        return False
    except Exception as e:
        lock_file.unlink(missing_ok=True)
        logger.error("%s/%s error: %s", media_slug, mode, e)
        return False


def _run_pipeline_background(
    cmd: list, project_dir: Path, media_slug: str, mode: str, lock_file: Path
) -> bool:
    """Run pipeline as background process (for long-running generate)."""
    try:
        log_file = project_dir / "state" / "logs" / "pipeline.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, "a") as log_fd:
            proc = subprocess.Popen(
                cmd, cwd=str(project_dir), env=_get_env(project_dir),
                stdout=log_fd, stderr=subprocess.STDOUT,
            )

        lock_file.write_text(str(proc.pid))
        logger.info("%s/%s started in background (pid %d)", media_slug, mode, proc.pid)

        # Notify that it started (completion will be detected by health monitor)
        _notify_managers(f"🔄 <b>{MEDIA_OUTLETS[media_slug].name}</b>: {mode} started (pid {proc.pid})")
        return True

    except Exception as e:
        lock_file.unlink(missing_ok=True)
        logger.error("%s/%s background start failed: %s", media_slug, mode, e)
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
