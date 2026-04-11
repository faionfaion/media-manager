"""Daily morning briefing — sent to management chats at start of day.

Summarizes yesterday's output, today's schedule, any issues.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import MANAGER_BOT_TOKEN, MEDIA_OUTLETS

logger = logging.getLogger(__name__)

# Track if briefing was already sent today
_briefing_sent_file = Path(__file__).resolve().parent.parent.parent / "logs" / ".briefing_sent"


def should_send_briefing() -> bool:
    """Check if morning briefing should be sent (once per day, after 7 UTC)."""
    now = datetime.now(timezone.utc)
    if now.hour < 7:
        return False

    today = now.strftime("%Y-%m-%d")
    if _briefing_sent_file.exists():
        last_date = _briefing_sent_file.read_text(encoding="utf-8").strip()
        if last_date == today:
            return False

    return True


def mark_briefing_sent() -> None:
    """Mark today's briefing as sent."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _briefing_sent_file.parent.mkdir(parents=True, exist_ok=True)
    _briefing_sent_file.write_text(today, encoding="utf-8")


def build_briefing() -> str:
    """Build morning briefing text."""
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    lines = [f"☀️ <b>Morning Briefing — {today}</b>\n"]

    for slug, cfg in MEDIA_OUTLETS.items():
        content_dir = cfg.project_dir / "content"
        state_dir = cfg.project_dir / "state"

        # Yesterday's articles
        yesterday_count = 0
        if content_dir.exists():
            for md in content_dir.glob("*.md"):
                try:
                    text = md.read_text(encoding="utf-8")[:500]
                    if f'date: "{yesterday}"' in text:
                        yesterday_count += 1
                except OSError:
                    pass

        # Yesterday's TG posts
        tg_count = 0
        tg_dir = state_dir / "tg_published"
        if tg_dir.exists():
            tg_file = tg_dir / f"{yesterday}.json"
            if tg_file.exists():
                try:
                    data = json.loads(tg_file.read_text(encoding="utf-8"))
                    tg_count = len(data) if isinstance(data, list) else len(data)
                except (json.JSONDecodeError, OSError):
                    pass

        # Today's plan
        plan_exists = False
        plan_count = 0
        plan_file = state_dir / "plans" / f"{today}.json"
        if plan_file.exists():
            plan_exists = True
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
                plan_count = len(plan.get("articles", []))
            except (json.JSONDecodeError, OSError):
                pass

        # Last run status
        runs_dir = state_dir / "runs"
        last_run = "—"
        last_ok = True
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                last_run = run_files[0].stem
                try:
                    rd = json.loads(run_files[0].read_text(encoding="utf-8"))
                    if rd.get("status") == "error" or rd.get("exit_code", 0) != 0:
                        last_ok = False
                except (json.JSONDecodeError, OSError):
                    pass

        status_icon = "✅" if last_ok else "❌"

        lines.append(
            f"<b>{cfg.name}</b> (@{cfg.tg_channel_username})\n"
            f"  Yesterday: {yesterday_count} articles, {tg_count} TG posts\n"
            f"  Today's plan: {'✅ ' + str(plan_count) + ' articles' if plan_exists else '⏳ not yet'}\n"
            f"  Last run: {status_icon} {last_run}\n"
        )

    # Schedule reminder
    lines.append("<b>Today's schedule:</b>")
    for slug, cfg in MEDIA_OUTLETS.items():
        lines.append(f"  {cfg.name}: gen {cfg.cron_generate}, pub {cfg.cron_publish or '—'}, digest {cfg.cron_digest}")

    return "\n".join(lines)


def send_briefing() -> None:
    """Build and send morning briefing to management chats."""
    from app.security.auth import get_management_chats
    import httpx

    text = build_briefing()
    chats = get_management_chats()

    if not chats:
        logger.warning("No management chats — briefing not sent")
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
            logger.error("Briefing send failed to %d: %s", chat_id, e)

    mark_briefing_sent()
    logger.info("Morning briefing sent to %d chats", len(chats))
