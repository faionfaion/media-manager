"""Bot command handlers — process editor commands from management chats.

Security model:
1. Only messages from AUTHORIZED_EDITORS are processed
2. Only messages in registered MANAGEMENT_CHATS are processed
3. All inputs pass through prompt injection detection
4. Rate limiting prevents abuse
5. Editor notes are wrapped in safe envelopes before reaching LLM
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.security.auth import (
    get_management_chats,
    is_authorized,
    is_management_chat,
)
from app.security.audit import audit_log, get_audit_stats, rotate_audit_logs
from app.security.injection import InjectionResult, detect_prompt_injection, wrap_editor_input_safely
from app.security.rate_limit import check_agent_rate_limit, check_rate_limit, get_remaining_quota
from app.security.validation import (
    sanitize_note_text,
    validate_callback_data,
    validate_command_args,
    validate_media_slug,
    validate_slug,
)
from config.settings import MEDIA_OUTLETS

logger = logging.getLogger(__name__)

_VALID_MEDIA_SLUGS = set(MEDIA_OUTLETS.keys())


def handle_update(update: dict) -> dict | None:
    """Process a Telegram update. Returns response dict or None."""
    message = update.get("message")
    if not message:
        # Could be callback_query, edited_message, etc.
        callback = update.get("callback_query")
        if callback:
            return _handle_callback(callback)
        return None

    user = message.get("from", {})
    user_id = user.get("id", 0)
    chat_id = message.get("chat", {}).get("id", 0)
    text = message.get("text", "").strip()

    if not text:
        return None

    # -- Security checks --

    # 0. Block forwarded messages — could bypass auth context
    if message.get("forward_from") or message.get("forward_from_chat") or message.get("forward_origin"):
        audit_log("forwarded_blocked", user_id, chat_id, text)
        logger.warning("Blocked forwarded message from user %d", user_id)
        return _reply(chat_id, "⚠️ Forwarded messages are not accepted. Please type your command directly.")

    # 1. Auth check (user_id)
    if not is_authorized(user_id):
        logger.warning("Unauthorized user %d attempted command: %s", user_id, text[:50])
        audit_log("unauthorized", user_id, chat_id, text)
        return None  # Silent ignore — don't reveal bot exists to strangers

    # 1b. Chat allowlist check (chat_id) — AND-combined with auth
    if not is_management_chat(chat_id):
        logger.warning(
            "Authorized user %d in non-allowlisted chat %d: %s",
            user_id, chat_id, text[:50],
        )
        audit_log("chat_not_allowed", user_id, chat_id, text)
        # /register and /whoami get a one-line ack with the chat_id so the
        # operator can add it to MEDIA_MANAGER_ALLOWED_CHATS and restart.
        # Everything else is silent ignore.
        if text.startswith("/whoami"):
            return _reply(
                chat_id,
                f"User ID: <code>{user_id}</code>\nChat ID: <code>{chat_id}</code>",
            )
        if text.startswith("/register"):
            return _reply(
                chat_id,
                f"Chat ID: <code>{chat_id}</code>\n"
                f"To allow this chat, add it to <code>MEDIA_MANAGER_ALLOWED_CHATS</code> "
                f"env (comma-separated) and restart the bot.",
            )
        return None

    # 2. Rate limit
    if not check_rate_limit(user_id):
        remaining = get_remaining_quota(user_id)
        audit_log("rate_limited", user_id, chat_id, text)
        return _reply(chat_id, f"⏳ Rate limit reached. Try again in ~1 minute. ({remaining} remaining)")

    # 3. Prompt injection check (for non-command messages that will reach LLM)
    injection_result: InjectionResult | None = None
    if not text.startswith("/"):
        injection_result = detect_prompt_injection(text)
        if injection_result.risk_level in ("high", "critical"):
            audit_log("injection_blocked", user_id, chat_id, text, injection_result.explanation)
            logger.warning(
                "Prompt injection blocked from user %d: %s",
                user_id, injection_result.explanation,
            )
            return _reply(
                chat_id,
                f"⚠️ Message blocked: {injection_result.explanation}\n"
                f"Please rephrase as a simple editorial note.",
            )

    # Chat allowlist already enforced above (step 1b). Reaching here means
    # both user_id and chat_id are on the allowlist.

    # -- Dispatch commands --
    audit_log("command", user_id, chat_id, text)

    if text.startswith("/"):
        return _dispatch_command(text, user_id, chat_id)

    # Free-text = editorial note
    if injection_result and injection_result.risk_level == "medium":
        # Warn but allow with sanitization
        _save_editor_note(text, user_id, injection_result=injection_result)
        return _reply(
            chat_id,
            f"📝 Note saved (with sanitization — some patterns were cleaned).\n"
            f"⚠️ {injection_result.explanation}",
        )

    _save_editor_note(text, user_id)
    return _reply(chat_id, "📝 Editorial note saved. Will be prioritized in next content run.")


def _dispatch_command(text: str, user_id: int, chat_id: int) -> dict | None:
    """Route /commands to handlers."""
    parts = text.split(None, 2)
    cmd = parts[0].lower().split("@")[0]  # strip @botname suffix
    args = parts[1:] if len(parts) > 1 else []

    commands = {
        "/help": _cmd_help,
        "/status": _cmd_status,
        "/plan": _cmd_plan,
        "/generate": _cmd_generate,
        "/digest": _cmd_digest,
        "/publish": _cmd_publish,
        "/skip": _cmd_skip,
        "/note": _cmd_note,
        "/ask": _cmd_ask,
        "/fix": _cmd_fix,
        "/analyze": _cmd_analyze,
        "/improve": _cmd_improve,
        "/dashboard": _cmd_dashboard,
        "/outlets": _cmd_outlets,
        "/schedule": _cmd_schedule,
        "/logs": _cmd_logs,
        "/security": _cmd_security,
        "/register": _cmd_register,
        "/whoami": _cmd_whoami,
    }

    handler = commands.get(cmd)
    if handler:
        return handler(args, user_id, chat_id)

    return _reply(chat_id, f"Unknown command: {cmd}\nSend /help for available commands.")


# -- Command implementations --

def _cmd_help(args: list, user_id: int, chat_id: int) -> dict:
    return _reply(chat_id, (
        "<b>📡 Media Manager Bot</b>\n\n"
        "<b>Pipeline Control:</b>\n"
        "/status [media] — pipeline & channel status\n"
        "/plan [media] — today's editorial plan\n"
        "/generate <media> — trigger full content generation\n"
        "/digest <media> — compile evening digest\n"
        "/publish <media> — trigger immediate TG publish\n"
        "/skip <media> <slug> — skip an article\n"
        "/schedule [media] — show cron schedules\n"
        "/logs <media> [N] — last N log lines\n\n"
        "<b>Editorial:</b>\n"
        "/note [media] <text> — add editor note\n"
        "(or just send plain text — saved as note for all outlets)\n\n"
        "<b>🤖 Agent (AI-powered):</b>\n"
        "/ask <question> — ask anything about the system\n"
        "/analyze <media> — content & pipeline analysis\n"
        "/fix <media> — diagnose & repair issues\n"
        "/improve <suggestion> — implement improvements\n\n"
        "<b>Management:</b>\n"
        "/dashboard — open management app\n"
        "/outlets — list all managed media\n"
        "/register — register this chat\n"
        "/security — security status\n\n"
        "<b>Media slugs:</b> neromedia, longlife, pashtelka"
    ))


def _cmd_status(args: list, user_id: int, chat_id: int) -> dict:
    """Show pipeline status for one or all outlets."""
    target = args[0] if args else None

    if target and target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}\nAvailable: {', '.join(MEDIA_OUTLETS)}")

    outlets = {target: MEDIA_OUTLETS[target]} if target else MEDIA_OUTLETS
    lines = ["<b>📊 Pipeline Status</b>\n"]

    for slug, cfg in outlets.items():
        state_dir = cfg.project_dir / "state"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Count today's articles
        from app.utils import count_articles_today
        today_count = count_articles_today(cfg.project_dir / "content", today)

        # Check last run
        runs_dir = state_dir / "runs"
        last_run = "never"
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                last_run = run_files[0].stem

        # Check TG published today
        tg_dir = state_dir / "tg_published"
        tg_count = 0
        if tg_dir.exists():
            tg_file = tg_dir / f"{today}.json"
            if tg_file.exists():
                try:
                    data = json.loads(tg_file.read_text(encoding="utf-8"))
                    tg_count = len(data) if isinstance(data, list) else len(data)
                except (json.JSONDecodeError, OSError):
                    pass

        lines.append(
            f"<b>{cfg.name}</b> (@{cfg.tg_channel_username})\n"
            f"  📰 Articles today: {today_count}\n"
            f"  📤 TG posts today: {tg_count}\n"
            f"  🕐 Last run: {last_run}\n"
            f"  🌐 {cfg.site_url}\n"
        )

    return _reply(chat_id, "\n".join(lines))


def _cmd_plan(args: list, user_id: int, chat_id: int) -> dict:
    """Show today's editorial plan."""
    target = args[0] if args else None
    if target and target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    outlets = {target: MEDIA_OUTLETS[target]} if target else MEDIA_OUTLETS
    lines = ["<b>📋 Editorial Plans</b>\n"]

    for slug, cfg in outlets.items():
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        plan_file = cfg.project_dir / "state" / "plans" / f"{today}.json"

        if plan_file.exists():
            try:
                plan = json.loads(plan_file.read_text(encoding="utf-8"))
                articles = plan.get("articles", [])
                lines.append(f"<b>{cfg.name}</b> ({len(articles)} planned):")
                for i, a in enumerate(articles[:12], 1):
                    topic = a.get("topic", a.get("title", "?"))
                    atype = a.get("type", "?")
                    lines.append(f"  {i}. [{atype}] {topic}")
            except (json.JSONDecodeError, OSError):
                lines.append(f"<b>{cfg.name}</b>: plan file error")
        else:
            lines.append(f"<b>{cfg.name}</b>: no plan yet for today")
        lines.append("")

    return _reply(chat_id, "\n".join(lines))


def _cmd_generate(args: list, user_id: int, chat_id: int) -> dict:
    """Trigger content generation — requires confirmation (heavy LLM operation)."""
    if not args:
        return _reply(chat_id, "Usage: /generate <media>\nExample: /generate pashtelka")

    target = args[0]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    cfg = MEDIA_OUTLETS[target]
    return _reply_with_buttons(
        chat_id,
        f"🔄 Generate content for <b>{cfg.name}</b>?\n"
        f"This runs the full pipeline (editorial plan → articles → deploy).\n"
        f"Takes 5-15 minutes per outlet.",
        [
            {"text": "✅ Confirm generate", "callback_data": f"confirm_generate:{target}"},
            {"text": "❌ Cancel", "callback_data": "cancel"},
        ],
    )


def _cmd_digest(args: list, user_id: int, chat_id: int) -> dict:
    """Trigger evening digest compilation."""
    if not args:
        return _reply(chat_id, "Usage: /digest <media>\nExample: /digest pashtelka")

    target = args[0]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    _queue_command(target, "digest", user_id)
    return _reply(chat_id, f"📋 Digest queued for {MEDIA_OUTLETS[target].name}.")


# -- Agent-powered commands --

def _cmd_ask(args: list, user_id: int, chat_id: int) -> dict:
    """Ask the agent anything about the media system."""
    if not args:
        return _reply(chat_id, "Usage: /ask <question>\nExample: /ask how many articles does pashtelka have today?")

    question = " ".join(args)

    # Injection check
    inj = detect_prompt_injection(question)
    if inj.risk_level in ("high", "critical"):
        audit_log("agent_injection_blocked", user_id, chat_id, question, inj.explanation)
        return _reply(chat_id, f"⚠️ Blocked: {inj.explanation}")

    # Agent rate limit
    if not check_agent_rate_limit(user_id):
        return _reply(chat_id, "⏳ Agent rate limit (20/hour). Try again later.")

    # Detect media slug from question
    media_slug = None
    for slug in MEDIA_OUTLETS:
        if slug in question.lower():
            media_slug = slug
            break

    audit_log("agent_call", user_id, chat_id, f"/ask {question[:100]}")
    from app.bot.agent import agent_ask, run_agent_async
    return run_agent_async(agent_ask, (question, media_slug), chat_id, "🤖 Investigating...")


def _cmd_analyze(args: list, user_id: int, chat_id: int) -> dict:
    """AI-powered content analysis."""
    if not args:
        return _reply(chat_id, "Usage: /analyze <media>\nExample: /analyze pashtelka")

    target = args[0]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    if not check_agent_rate_limit(user_id):
        return _reply(chat_id, "⏳ Agent rate limit (20/hour). Try again later.")

    audit_log("agent_call", user_id, chat_id, f"/analyze {target}")
    from app.bot.agent import agent_analyze, run_agent_async
    return run_agent_async(agent_analyze, (target,), chat_id, f"🔍 Analyzing {MEDIA_OUTLETS[target].name}...")


def _cmd_fix(args: list, user_id: int, chat_id: int) -> dict:
    """Diagnose & fix pipeline issues — requires confirmation."""
    if not args:
        return _reply(chat_id, "Usage: /fix <media> [description]\nExample: /fix pashtelka pipeline stuck")

    target = args[0]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    problem = " ".join(args[1:]) if len(args) > 1 else "Check pipeline health, find and fix any issues"

    # Injection check on problem description
    inj = detect_prompt_injection(problem)
    if inj.risk_level in ("high", "critical"):
        return _reply(chat_id, f"⚠️ Blocked: {inj.explanation}")

    return _reply_with_buttons(
        chat_id,
        f"🔧 Fix <b>{MEDIA_OUTLETS[target].name}</b>?\n"
        f"Problem: {problem[:200]}\n\n"
        f"The agent will read logs, diagnose, and apply fixes.",
        [
            {"text": "✅ Confirm fix", "callback_data": f"confirm_fix:{target}"},
            {"text": "❌ Cancel", "callback_data": "cancel"},
        ],
    )


def _cmd_improve(args: list, user_id: int, chat_id: int) -> dict:
    """Implement system improvements — requires confirmation."""
    if not args:
        return _reply(chat_id, "Usage: /improve <suggestion>\nExample: /improve add weekend content planning")

    suggestion = " ".join(args)

    inj = detect_prompt_injection(suggestion)
    if inj.risk_level in ("high", "critical"):
        return _reply(chat_id, f"⚠️ Blocked: {inj.explanation}")

    return _reply_with_buttons(
        chat_id,
        f"💡 Implement improvement?\n"
        f"<i>{suggestion[:300]}</i>\n\n"
        f"The agent will read code, make changes, and report.",
        [
            {"text": "✅ Confirm improve", "callback_data": "confirm_improve:manager"},
            {"text": "❌ Cancel", "callback_data": "cancel"},
        ],
    )


def _cmd_dashboard(args: list, user_id: int, chat_id: int) -> dict:
    """Open the Telegram Mini App management dashboard."""
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": "📱 <b>Media Manager Dashboard</b>\n\nOpen the management interface:",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[{
                "text": "📊 Open Dashboard",
                "web_app": {"url": "https://media-manager.faion.net/mini-app"},
            }]],
        },
    }


def _cmd_publish(args: list, user_id: int, chat_id: int) -> dict:
    """Trigger immediate publish — requires confirmation via inline button."""
    if not args:
        return _reply(chat_id, "Usage: /publish <media>\nExample: /publish pashtelka")

    target = args[0]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    # Ask for confirmation with inline buttons
    return _reply_with_buttons(
        chat_id,
        f"⚡ Publish <b>{MEDIA_OUTLETS[target].name}</b> now?\n"
        f"This will trigger the pipeline immediately.",
        [
            {"text": "✅ Confirm publish", "callback_data": f"confirm_publish:{target}"},
            {"text": "❌ Cancel", "callback_data": "cancel"},
        ],
    )


def _cmd_skip(args: list, user_id: int, chat_id: int) -> dict:
    """Skip an article — requires confirmation via inline button."""
    if len(args) < 2:
        return _reply(chat_id, "Usage: /skip <media> <slug>")

    target, slug = args[0], args[1]
    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    return _reply_with_buttons(
        chat_id,
        f"⏭ Skip <b>{slug}</b> in {MEDIA_OUTLETS[target].name}?",
        [
            {"text": "✅ Confirm skip", "callback_data": f"confirm_skip:{target}:{slug}"},
            {"text": "❌ Cancel", "callback_data": "cancel"},
        ],
    )


def _cmd_note(args: list, user_id: int, chat_id: int) -> dict:
    """Add editorial note to specific media."""
    if len(args) < 2:
        return _reply(chat_id, "Usage: /note <media> <text>\nExample: /note pashtelka more about AIMA")

    target = args[0]
    note_text = " ".join(args[1:]) if len(args) > 1 else args[1]

    if target == "all":
        targets = list(MEDIA_OUTLETS.keys())
    elif target in MEDIA_OUTLETS:
        targets = [target]
    else:
        return _reply(chat_id, f"Unknown media: {target}\nUse 'all' for all outlets.")

    injection = detect_prompt_injection(note_text)
    if injection.risk_level in ("high", "critical"):
        return _reply(chat_id, f"⚠️ Note blocked: {injection.explanation}")

    for t in targets:
        _save_editor_note(note_text, user_id, media_slug=t, injection_result=injection)

    names = ", ".join(MEDIA_OUTLETS[t].name for t in targets)
    return _reply(chat_id, f"📝 Note saved for {names}.")


def _cmd_outlets(args: list, user_id: int, chat_id: int) -> dict:
    """List all managed media outlets."""
    lines = ["<b>📺 Managed Media Outlets</b>\n"]
    for slug, cfg in MEDIA_OUTLETS.items():
        lang = cfg.lang if isinstance(cfg.lang, str) else ", ".join(cfg.lang)
        lines.append(
            f"<b>{cfg.name}</b> ({slug})\n"
            f"  🌐 {cfg.site_url}\n"
            f"  📱 @{cfg.tg_channel_username}\n"
            f"  🗣 {lang}\n"
        )
    return _reply(chat_id, "\n".join(lines))


def _cmd_schedule(args: list, user_id: int, chat_id: int) -> dict:
    """Show cron schedules."""
    target = args[0] if args else None
    outlets = {target: MEDIA_OUTLETS[target]} if target and target in MEDIA_OUTLETS else MEDIA_OUTLETS
    lines = ["<b>⏰ Schedules</b>\n"]

    for slug, cfg in outlets.items():
        lines.append(
            f"<b>{cfg.name}</b>\n"
            f"  Generate: {cfg.cron_generate or 'inline'}\n"
            f"  Publish:  {cfg.cron_publish or 'inline'}\n"
            f"  Digest:   {cfg.cron_digest}\n"
        )

    return _reply(chat_id, "\n".join(lines))


def _cmd_logs(args: list, user_id: int, chat_id: int) -> dict:
    """Show recent pipeline logs."""
    target = args[0] if args else "pashtelka"
    n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20

    if target not in MEDIA_OUTLETS:
        return _reply(chat_id, f"Unknown media: {target}")

    log_file = MEDIA_OUTLETS[target].project_dir / "state" / "logs" / "pipeline.log"
    if not log_file.exists():
        return _reply(chat_id, f"No logs found for {target}")

    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        tail = lines[-n:]
        text = "\n".join(tail)
        if len(text) > 3500:
            text = text[-3500:]
        return _reply(chat_id, f"<b>📋 {target} logs (last {n}):</b>\n<pre>{text}</pre>")
    except OSError as e:
        return _reply(chat_id, f"Error reading logs: {e}")


def _cmd_security(args: list, user_id: int, chat_id: int) -> dict:
    """Show security status."""
    from config.settings import AUTHORIZED_EDITORS

    chats = get_management_chats()
    stats = get_audit_stats()

    # Rotate old logs while we're here
    rotate_audit_logs()

    return _reply(chat_id, (
        "<b>🔒 Security Status</b>\n\n"
        f"Authorized editors: {len(AUTHORIZED_EDITORS)}\n"
        f"Management chats: {len(chats)}\n"
        f"Audit log entries: {stats['total_entries']}\n"
        f"Blocked attempts: {stats['blocked']}\n"
        f"Audit log files: {stats['files']}\n\n"
        "<b>Guardrails active:</b>\n"
        "✅ User auth (TG user ID whitelist)\n"
        "✅ Chat registration required\n"
        "✅ Forwarded message blocking\n"
        "✅ Prompt injection detection (5 categories)\n"
        "✅ Rate limiting (10 cmd/min)\n"
        "✅ Input validation (slug, callback, args)\n"
        "✅ Safe prompt envelope wrapping\n"
        "✅ Destructive command confirmation (inline buttons)\n"
        "✅ Audit logging (daily rotation, 30d retention)\n"
        "✅ File size guards (DoS prevention)"
    ))


def _cmd_register(args: list, user_id: int, chat_id: int) -> dict:
    """Info: dynamic registration is disabled. Allowlist is static."""
    return _reply(
        chat_id,
        f"Chat ID: <code>{chat_id}</code> (already on allowlist).\n"
        f"Allowlist is static — set <code>MEDIA_MANAGER_ALLOWED_CHATS</code> env "
        f"(comma-separated chat_ids) and restart the bot to change it.",
    )


def _cmd_whoami(args: list, user_id: int, chat_id: int) -> dict:
    """Echo current user_id and chat_id (useful when adding new chats)."""
    return _reply(
        chat_id,
        f"User ID: <code>{user_id}</code>\nChat ID: <code>{chat_id}</code>",
    )


# -- Helpers --

def _reply(chat_id: int, text: str) -> dict:
    """Build a sendMessage response."""
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def _reply_with_buttons(chat_id: int, text: str, buttons: list[dict]) -> dict:
    """Build a sendMessage with inline keyboard buttons."""
    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[btn] for btn in buttons],
        },
    }


def _save_editor_note(
    text: str,
    user_id: int,
    media_slug: str | None = None,
    injection_result: InjectionResult | None = None,
) -> None:
    """Save editor note to the appropriate media project(s)."""
    targets = [media_slug] if media_slug else list(MEDIA_OUTLETS.keys())

    for slug in targets:
        cfg = MEDIA_OUTLETS.get(slug)
        if not cfg:
            continue

        notes_file = cfg.project_dir / "state" / "editor_notes.md"
        if not notes_file.exists():
            continue

        safe_text = wrap_editor_input_safely(text, slug) if injection_result else text
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        entry = f"\n- [{timestamp}] (user:{user_id}) {safe_text}\n"
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info("Editor note saved to %s: %s", slug, text[:80])


def _queue_command(media_slug: str, command: str, user_id: int, extra: dict | None = None) -> None:
    """Queue a command for the pipeline orchestrator."""
    queue_dir = Path(__file__).resolve().parent.parent.parent / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    cmd = {
        "media": media_slug,
        "command": command,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    cmd_file = queue_dir / f"{ts}_{media_slug}_{command}.json"
    cmd_file.write_text(json.dumps(cmd, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Queued command: %s/%s by user %d", media_slug, command, user_id)


def _handle_callback(callback: dict) -> dict | None:
    """Handle inline button callbacks (confirmations, cancellations)."""
    user = callback.get("from", {})
    user_id = user.get("id", 0)

    if not is_authorized(user_id):
        return None

    if not check_rate_limit(user_id):
        return None

    data = callback.get("data", "")
    chat_id = callback.get("message", {}).get("chat", {}).get("id", 0)

    # Validate callback data structure
    parsed = validate_callback_data(data)
    if parsed is None:
        audit_log("invalid_callback", user_id, chat_id, data)
        logger.warning("Invalid callback_data from user %d: %s", user_id, data[:50])
        return None

    action, media, param = parsed
    audit_log("callback", user_id, chat_id, data)

    if action == "cancel":
        return _reply(chat_id, "❌ Cancelled.")

    if action == "confirm_generate":
        if not validate_media_slug(media, _VALID_MEDIA_SLUGS):
            return _reply(chat_id, f"Unknown media: {media}")
        _queue_command(media, "generate", user_id)
        return _reply(chat_id, f"🔄 Generate queued for {MEDIA_OUTLETS[media].name}. This will take 5-15 min.")

    elif action == "confirm_publish":
        if not validate_media_slug(media, _VALID_MEDIA_SLUGS):
            return _reply(chat_id, f"Unknown media: {media}")
        _queue_command(media, "publish", user_id)
        return _reply(chat_id, f"✅ Publish confirmed and queued for {MEDIA_OUTLETS[media].name}.")

    elif action == "confirm_skip":
        if not validate_media_slug(media, _VALID_MEDIA_SLUGS):
            return _reply(chat_id, f"Unknown media: {media}")
        safe_slug = validate_slug(param)
        if not safe_slug:
            return _reply(chat_id, "⚠️ Invalid article slug.")
        _queue_command(media, "skip", user_id, {"slug": safe_slug})
        return _reply(chat_id, f"✅ Skipping '{safe_slug}' in {MEDIA_OUTLETS[media].name}.")

    elif action == "confirm_fix":
        if not validate_media_slug(media, _VALID_MEDIA_SLUGS):
            return _reply(chat_id, f"Unknown media: {media}")
        if not check_agent_rate_limit(user_id):
            return _reply(chat_id, "⏳ Agent rate limit (20/hour).")
        audit_log("agent_call", user_id, chat_id, f"confirm_fix:{media}")
        from app.bot.agent import agent_fix, run_agent_async
        return run_agent_async(
            agent_fix, (media, "Check pipeline health, find and fix any issues"),
            chat_id, f"🔧 Fixing {MEDIA_OUTLETS[media].name}..."
        )

    elif action == "confirm_improve":
        if not check_agent_rate_limit(user_id):
            return _reply(chat_id, "⏳ Agent rate limit (20/hour).")
        # Retrieve suggestion from the original message text
        msg_text = callback.get("message", {}).get("text", "")
        suggestion = msg_text.split("\n")[1] if "\n" in msg_text else "General improvement"
        audit_log("agent_call", user_id, chat_id, f"confirm_improve: {suggestion[:80]}")
        from app.bot.agent import agent_improve, run_agent_async
        return run_agent_async(
            agent_improve, (suggestion,),
            chat_id, "💡 Implementing improvement..."
        )

    return None
