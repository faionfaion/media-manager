"""Pipeline health monitor — detects failures and missed schedules.

Called periodically by the cron orchestrator. Sends alerts to management chats.
Also detects completion/failure of background pipeline processes.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import MANAGER_BOT_TOKEN, MEDIA_OUTLETS

logger = logging.getLogger(__name__)

# Track last alert times to avoid spam (in-memory, resets on restart)
_last_alerts: dict[str, datetime] = {}
ALERT_COOLDOWN = timedelta(hours=1)


_LOCK_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def check_background_processes() -> list[str]:
    """Detect completed/failed background pipeline processes."""
    alerts: list[str] = []

    for lock_file in _LOCK_DIR.glob(".lock_*"):
        # Parse: .lock_{media}_{mode}
        parts = lock_file.stem.lstrip(".lock_").split("_", 1)
        if len(parts) < 2:
            continue
        media_slug, mode = parts[0], parts[1]

        try:
            pid = int(lock_file.read_text().strip())
        except (ValueError, OSError):
            lock_file.unlink(missing_ok=True)
            continue

        # Check if process is still running
        try:
            os.kill(pid, 0)
            # Still running — no alert
        except OSError:
            # Process finished — check exit status via /proc or just report
            lock_file.unlink(missing_ok=True)
            cfg = MEDIA_OUTLETS.get(media_slug)
            name = cfg.name if cfg else media_slug

            alert_key = f"bg_done_{media_slug}_{mode}_{pid}"
            if _should_alert(alert_key):
                alerts.append(
                    f"✅ <b>{name}</b>: background {mode} completed (pid {pid})"
                )

    return alerts


def check_pipeline_health() -> list[str]:
    """Check all pipelines for issues. Returns list of alert messages."""
    # First check background processes
    alerts: list[str] = check_background_processes()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    for slug, cfg in MEDIA_OUTLETS.items():
        state_dir = cfg.project_dir / "state"
        content_dir = cfg.project_dir / "content"

        # 1. Check if generate ran today (by looking for today's content)
        today_articles = 0
        if content_dir.exists():
            for md in content_dir.glob("*.md"):
                try:
                    text = md.read_text(encoding="utf-8")[:500]
                    if f'date: "{today}"' in text:
                        today_articles += 1
                except OSError:
                    pass

        # Alert if no articles by noon UTC
        if now.hour >= 12 and today_articles == 0:
            alert_key = f"{slug}_no_articles_{today}"
            if _should_alert(alert_key):
                alerts.append(
                    f"⚠️ <b>{cfg.name}</b>: no articles generated today ({today}). "
                    f"Expected generate to run at {cfg.cron_generate}."
                )

        # 2. Check last pipeline run age
        runs_dir = state_dir / "runs"
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                last_run_name = run_files[0].stem
                try:
                    # Parse timestamp from filename: 2026-04-11_081224
                    last_dt = datetime.strptime(last_run_name, "%Y-%m-%d_%H%M%S").replace(tzinfo=timezone.utc)
                    age = now - last_dt
                    if age > timedelta(hours=26):
                        alert_key = f"{slug}_stale_run_{today}"
                        if _should_alert(alert_key):
                            alerts.append(
                                f"⚠️ <b>{cfg.name}</b>: last pipeline run was {age.total_seconds()/3600:.0f}h ago "
                                f"({last_run_name}). Pipeline may be stuck."
                            )
                except ValueError:
                    pass

        # 3. Check for error in last run
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                try:
                    run_data = json.loads(run_files[0].read_text(encoding="utf-8"))
                    if run_data.get("status") == "error" or run_data.get("exit_code", 0) != 0:
                        alert_key = f"{slug}_error_{run_files[0].stem}"
                        if _should_alert(alert_key):
                            error_msg = run_data.get("error", "unknown error")[:200]
                            alerts.append(
                                f"❌ <b>{cfg.name}</b>: last run failed.\n"
                                f"<pre>{error_msg}</pre>"
                            )
                except (json.JSONDecodeError, OSError):
                    pass

        # 4. Check pipeline log for recent errors
        log_file = state_dir / "logs" / "pipeline.log"
        if log_file.exists():
            try:
                lines = log_file.read_text(encoding="utf-8").splitlines()
                recent_errors = [
                    l for l in lines[-50:]
                    if "ERROR" in l or "CRITICAL" in l or "Traceback" in l
                ]
                if len(recent_errors) >= 3:
                    alert_key = f"{slug}_log_errors_{today}_{now.hour}"
                    if _should_alert(alert_key):
                        sample = recent_errors[-1][:150]
                        alerts.append(
                            f"🔴 <b>{cfg.name}</b>: {len(recent_errors)} errors in recent logs.\n"
                            f"Last: <pre>{sample}</pre>"
                        )
            except OSError:
                pass

    return alerts


def send_alerts(alerts: list[str]) -> None:
    """Send alert messages to all management chats."""
    if not alerts:
        return

    from app.security.auth import get_management_chats
    import httpx

    chats = get_management_chats()
    if not chats:
        logger.warning("No management chats registered — alerts not delivered")
        return

    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
    combined = "\n\n".join(alerts)
    header = f"🏥 <b>Pipeline Health Check</b> ({datetime.now(timezone.utc).strftime('%H:%M UTC')})\n\n"
    text = header + combined

    for chat_id in chats:
        try:
            resp = httpx.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
            if not resp.json().get("ok"):
                logger.error("Alert delivery failed to %d: %s", chat_id, resp.text[:200])
        except Exception as e:
            logger.error("Alert delivery error to %d: %s", chat_id, e)


def _should_alert(key: str) -> bool:
    """Check cooldown to prevent alert spam."""
    now = datetime.now(timezone.utc)
    last = _last_alerts.get(key)
    if last and (now - last) < ALERT_COOLDOWN:
        return False
    _last_alerts[key] = now
    return True
