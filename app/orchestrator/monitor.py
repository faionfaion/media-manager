"""Pipeline health monitor with auto-healing.

Called every 20 minutes by the cron orchestrator.
Detects issues → launches healing agent (Claude SDK) → reports fixes to TG.
Only sends TG messages when something was FIXED, not status spam.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import MANAGER_BOT_TOKEN, MEDIA_OUTLETS

logger = logging.getLogger(__name__)

# Cooldown per alert key (in-memory, resets on restart)
_last_alerts: dict[str, datetime] = {}
HEAL_COOLDOWN = timedelta(hours=2)  # don't re-heal same issue within 2h

_LOCK_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

def detect_issues() -> list[dict]:
    """Scan all pipelines for actionable issues. Returns list of issue dicts."""
    issues: list[dict] = []
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Check background process completions first
    for lock_file in _LOCK_DIR.glob(".lock_*"):
        parts = lock_file.stem.lstrip(".lock_").split("_", 1)
        if len(parts) < 2:
            continue
        media_slug, mode = parts[0], parts[1]
        try:
            pid = int(lock_file.read_text().strip())
        except (ValueError, OSError):
            lock_file.unlink(missing_ok=True)
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            lock_file.unlink(missing_ok=True)
            logger.info("Background %s/%s (pid %d) completed", media_slug, mode, pid)

    for slug, cfg in MEDIA_OUTLETS.items():
        state_dir = cfg.project_dir / "state"
        runs_dir = state_dir / "runs"

        # --- Issue: stale lock file ---
        for mode in ("generate", "publish", "digest"):
            lock = Path(f"/tmp/{slug}-{mode}.lock")
            if lock.exists():
                try:
                    pid = int(lock.read_text().strip())
                    os.kill(pid, 0)
                except (ValueError, OSError):
                    issues.append({
                        "slug": slug,
                        "type": "stale_lock",
                        "severity": "high",
                        "detail": f"Stale lock /tmp/{slug}-{mode}.lock (pid dead)",
                        "auto_fix": f"rm /tmp/{slug}-{mode}.lock",
                    })

        # --- Issue: last run failed ---
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                try:
                    rd = json.loads(run_files[0].read_text(encoding="utf-8"))
                    status = rd.get("exit_status", rd.get("status", "ok"))
                    if status == "error":
                        error_msg = rd.get("error", "unknown")[:300]
                        failed_stage = rd.get("failed_stage", "?")
                        issues.append({
                            "slug": slug,
                            "type": "last_run_failed",
                            "severity": "high",
                            "detail": f"Last run failed at {failed_stage}: {error_msg}",
                            "run_file": run_files[0].name,
                        })
                except (json.JSONDecodeError, OSError):
                    pass

        # --- Issue: pipeline stale (no run in 26h) ---
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                try:
                    last_dt = datetime.strptime(
                        run_files[0].stem, "%Y-%m-%d_%H%M%S"
                    ).replace(tzinfo=timezone.utc)
                    age_h = (now - last_dt).total_seconds() / 3600
                    if age_h > 26:
                        issues.append({
                            "slug": slug,
                            "type": "stale_pipeline",
                            "severity": "medium",
                            "detail": f"Last run {age_h:.0f}h ago ({run_files[0].stem})",
                        })
                except ValueError:
                    pass

        # --- Issue: no articles today (after noon, only if pipeline expected to run) ---
        if now.hour >= 12 and cfg.cron_generate:
            from app.utils import count_articles_today
            content_dir = cfg.project_dir / "content"
            today_articles = count_articles_today(content_dir, today)
            if today_articles == 0:
                # Don't flag if last run errored (already captured above)
                already_flagged = any(
                    i["slug"] == slug and i["type"] == "last_run_failed"
                    for i in issues
                )
                if not already_flagged:
                    issues.append({
                        "slug": slug,
                        "type": "no_articles_today",
                        "severity": "medium",
                        "detail": f"0 articles today, expected generate at {cfg.cron_generate}",
                    })

    return issues


# ---------------------------------------------------------------------------
# Auto-healing
# ---------------------------------------------------------------------------

def heal_issues(issues: list[dict]) -> list[str]:
    """Attempt to auto-heal detected issues. Returns list of TG report messages."""
    if not issues:
        return []

    reports: list[str] = []

    # Group simple fixes (stale locks) — handle without agent
    for issue in issues:
        key = f"{issue['slug']}_{issue['type']}"
        if not _should_heal(key):
            continue

        if issue["type"] == "stale_lock":
            # Direct fix — remove stale lock
            cmd = issue.get("auto_fix", "")
            if cmd.startswith("rm "):
                lock_path = Path(cmd[3:])
                if lock_path.exists():
                    lock_path.unlink()
                    reports.append(
                        f"🔧 <b>{_name(issue['slug'])}</b>: removed stale lock\n"
                        f"<pre>{issue['detail']}</pre>"
                    )
                    logger.info("Auto-healed: removed %s", lock_path)

    # Complex issues → healing agent
    agent_issues = [
        i for i in issues
        if i["type"] in ("last_run_failed", "stale_pipeline", "no_articles_today")
        and _should_heal(f"{i['slug']}_{i['type']}")
    ]

    if agent_issues:
        report = _run_healing_agent(agent_issues)
        if report:
            reports.append(report)

    return reports


def _run_healing_agent(issues: list[dict]) -> str | None:
    """Launch Claude Agent SDK to diagnose and fix pipeline issues."""
    try:
        from app.bot.agent import _run_with_retry, _async_agent, TOOLS_FIX

        # Build issue summary for the agent
        issue_lines = []
        slugs = set()
        for i in issues:
            cfg = MEDIA_OUTLETS.get(i["slug"])
            name = cfg.name if cfg else i["slug"]
            issue_lines.append(f"- {name} ({i['slug']}): [{i['type']}] {i['detail']}")
            slugs.add(i["slug"])

        issues_text = "\n".join(issue_lines)

        system_prompt = _build_healer_system_prompt()
        prompt = (
            f"You are the auto-healing agent for Faion media pipelines.\n\n"
            f"## Detected issues\n\n{issues_text}\n\n"
            f"## Instructions\n\n"
            f"1. Investigate each issue: read logs, run reports, state files\n"
            f"2. For each fixable issue, apply the fix:\n"
            f"   - stale_lock: remove the lock file\n"
            f"   - last_run_failed: check logs, fix config/state if possible, "
            f"retry pipeline if error was transient\n"
            f"   - stale_pipeline: check if cron is firing, check locks, "
            f"check if orchestrator is reaching this outlet\n"
            f"   - no_articles_today: check if generate ran, check state, "
            f"retry generate if it didn't run\n"
            f"3. Do NOT run full pipeline generate (too long). "
            f"Only fix state, config, locks, or retry specific stages.\n"
            f"4. After fixing, respond with ONLY this JSON:\n\n"
            f"```json\n"
            f'{{"healed": [{{"slug": "...", "issue": "...", "action": "...", "result": "fixed|skipped|failed"}}], '
            f'"summary": "one sentence overall"}}\n'
            f"```"
        )

        # Use first issue's slug for CWD
        first_slug = list(slugs)[0]
        cwd = str(MEDIA_OUTLETS[first_slug].project_dir) if first_slug in MEDIA_OUTLETS else "/tmp"

        raw = _run_with_retry(
            lambda: _async_agent(prompt, system_prompt, "opus", cwd, TOOLS_FIX),
            "auto-heal",
        )

        return _format_heal_report(raw, issues)

    except Exception as e:
        logger.error("Healing agent failed: %s", e)
        return f"❌ Healing agent error: {e}"


def _format_heal_report(raw: str, issues: list[dict]) -> str | None:
    """Parse agent response and format TG message."""
    import re

    # Try to extract JSON from response
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            data = json.loads(match.group())
            healed = data.get("healed", [])
            summary = data.get("summary", "")

            if not healed:
                return None  # Nothing was done

            lines = [f"🔧 <b>Auto-Heal Report</b> ({datetime.now(timezone.utc).strftime('%H:%M UTC')})\n"]

            for h in healed:
                icon = {"fixed": "✅", "skipped": "⏭", "failed": "❌"}.get(h.get("result", ""), "❓")
                name = _name(h.get("slug", ""))
                lines.append(f"{icon} <b>{name}</b>: {h.get('action', '?')}")

            if summary:
                lines.append(f"\n📋 {summary}")

            return "\n".join(lines)

        except json.JSONDecodeError:
            pass

    # Fallback: just show raw agent output (truncated)
    if raw.strip():
        truncated = raw[:1500] if len(raw) > 1500 else raw
        return (
            f"🔧 <b>Auto-Heal Report</b>\n\n"
            f"<pre>{_escape_html(truncated)}</pre>"
        )

    return None


def _build_healer_system_prompt() -> str:
    """System prompt for healing agent — focused on fixing, not investigating."""
    outlet_sections = []
    for slug, cfg in MEDIA_OUTLETS.items():
        outlet_sections.append(
            f"- {cfg.name} ({slug}): dir={cfg.project_dir}, "
            f"gen={cfg.cron_generate}, site={cfg.site_url}"
        )

    return (
        "You are an auto-healing agent for Faion media pipelines.\n"
        "Your job: fix issues quickly and report what you did.\n\n"
        "Outlets:\n" + "\n".join(outlet_sections) + "\n\n"
        "Key paths per outlet:\n"
        "- state/logs/pipeline.log — pipeline log\n"
        "- state/logs/cron.log — cron log\n"
        "- state/runs/*.json — run reports (exit_status, error, failed_stage)\n"
        "- state/editor_notes.md — editor notes\n"
        "- pipeline/config.py — pipeline config\n\n"
        "Lock files: /tmp/{slug}-{mode}.lock\n\n"
        "Safety:\n"
        "- DO remove stale locks (PID dead)\n"
        "- DO fix state files (JSON, summaries)\n"
        "- DO restart failed stages via: cd {dir} && python3 -m pipeline publish -v\n"
        "- DO NOT run full generate (takes 30+ min)\n"
        "- DO NOT modify security code\n"
        "- DO NOT expose secrets\n"
        "- Prefer minimal changes. Explain what you did."
    )


# ---------------------------------------------------------------------------
# Main entry point (called by orchestrator)
# ---------------------------------------------------------------------------

def check_and_heal() -> None:
    """Main entry: detect issues → heal → report to TG."""
    issues = detect_issues()

    if not issues:
        logger.debug("Health check: all systems OK")
        return

    logger.info("Health check: %d issues detected", len(issues))
    for i in issues:
        logger.info("  [%s] %s: %s", i["severity"], i["slug"], i["detail"])

    reports = heal_issues(issues)

    if reports:
        _send_reports(reports)


# ---------------------------------------------------------------------------
# Legacy compat: keep check_pipeline_health for other callers
# ---------------------------------------------------------------------------

def check_pipeline_health() -> list[str]:
    """Legacy: returns alert strings. Now just wraps detect_issues."""
    issues = detect_issues()
    return [f"⚠️ <b>{_name(i['slug'])}</b>: {i['detail']}" for i in issues]


def check_background_processes() -> list[str]:
    """Legacy: detect completed background processes."""
    return []  # Now handled in detect_issues()


# ---------------------------------------------------------------------------
# TG messaging
# ---------------------------------------------------------------------------

def _send_reports(reports: list[str]) -> None:
    """Send heal reports to management chats."""
    if not reports:
        return

    from app.security.auth import get_management_chats
    import httpx

    chats = get_management_chats()
    if not chats:
        logger.warning("No management chats — reports not delivered")
        return

    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
    text = "\n\n".join(reports)

    for chat_id in chats:
        try:
            resp = httpx.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": True,  # silent — don't spam
            }, timeout=10)
            if not resp.json().get("ok"):
                logger.error("Report delivery failed to %d: %s", chat_id, resp.text[:200])
        except Exception as e:
            logger.error("Report delivery error to %d: %s", chat_id, e)


# Keep legacy send_alerts for backward compat
send_alerts = _send_reports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name(slug: str) -> str:
    """Get display name for outlet slug."""
    cfg = MEDIA_OUTLETS.get(slug)
    return cfg.name if cfg else slug


def _escape_html(text: str) -> str:
    """Escape HTML special chars for TG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _should_heal(key: str) -> bool:
    """Check cooldown to prevent re-healing same issue."""
    now = datetime.now(timezone.utc)
    last = _last_alerts.get(key)
    if last and (now - last) < HEAL_COOLDOWN:
        return False
    _last_alerts[key] = now
    return True
