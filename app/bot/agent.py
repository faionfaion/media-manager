"""Agent SDK wrapper for intelligent bot operations.

Adapts the proven pipeline/sdk.py pattern from neromedia to the
media-manager context. Provides 4 agent functions:
- agent_ask: read-only investigation
- agent_fix: diagnose and repair pipeline issues
- agent_analyze: structured content analysis
- agent_improve: implement system improvements
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
import threading
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query as sdk_query
from claude_agent_sdk.types import AssistantMessage, TextBlock

from config.settings import (
    AGENT_ALLOWED_DIRS,
    AGENT_MODEL,
    AGENT_RETRY_BASE_DELAY,
    AGENT_RETRY_MAX,
    AGENT_RETRY_MAX_DELAY,
    AGENT_TIMEOUT,
    MANAGER_BOT_TOKEN,
    MEDIA_OUTLETS,
)

logger = logging.getLogger(__name__)


def _patch_sdk_parser() -> None:
    """Patch claude_code_sdk to skip unknown message types (e.g. rate_limit_event)."""
    try:
        from claude_code_sdk._internal import message_parser, client
        _original = message_parser.parse_message

        def _safe_parse(data):
            try:
                return _original(data)
            except Exception:
                logger.debug("Skipping unknown SDK message type: %s", data.get("type", "?"))
                return None

        message_parser.parse_message = _safe_parse
        client.parse_message = _safe_parse
    except Exception as e:
        logger.warning("Could not patch SDK parser: %s", e)


_patch_sdk_parser()

_ALL_BUILTIN_TOOLS = [
    "Read", "Glob", "Grep", "Bash", "Write", "Edit",
    "WebSearch", "WebFetch", "Agent", "TodoWrite", "TodoRead",
    "NotebookEdit", "LSP",
]

# Tool profiles per command
TOOLS_ASK = ["Read", "Glob", "Grep", "Bash"]  # read-only
TOOLS_FIX = ["Read", "Edit", "Bash", "Glob", "Grep"]  # can modify
TOOLS_IMPROVE = ["Read", "Edit", "Bash", "Glob", "Grep", "WebSearch"]

# System prompt with full knowledge of all pipelines
def _build_system_prompt() -> str:
    """Build system prompt dynamically from MEDIA_OUTLETS config."""
    manager_dir = Path(__file__).resolve().parent.parent.parent
    outlet_sections = []
    for slug, cfg in MEDIA_OUTLETS.items():
        lang = cfg.lang if isinstance(cfg.lang, str) else ", ".join(cfg.lang)
        outlet_sections.append(
            f"### {cfg.name} ({slug})\n"
            f"- Dir: {cfg.project_dir}\n"
            f"- Site: {cfg.site_url}\n"
            f"- TG: @{cfg.tg_channel_username}\n"
            f"- Lang: {lang}\n"
            f"- Schedule: gen {cfg.cron_generate}, pub {cfg.cron_publish or 'inline'}, digest {cfg.cron_digest}\n"
            f"- Content: content/ (markdown)\n"
            f"- State: state/ (plans, runs, logs, editor_notes.md)"
        )

    return f"""You are the Media Manager agent for Faion Network media pipelines.
You manage {len(MEDIA_OUTLETS)} media outlets:

## Outlets

{chr(10).join(outlet_sections)}

## Media Manager
- Dir: {manager_dir}
- Config: config/settings.py
- Bot handlers: app/bot/handlers.py
- Security: app/security/ (injection detection, auth, validation, audit)
- Orchestrator: app/orchestrator/ (runner, monitor, briefing)

## Common patterns
- Pipeline entry: `python3 -m pipeline <mode> -v` (modes: generate, publish, digest)
- State dir has: plans/, runs/, logs/pipeline.log, editor_notes.md
- Content dir: markdown files with YAML frontmatter (title, date, type, tags)
- Config: pipeline/config.py (models, schedules, RSS feeds, author, topics)

## Safety rules
- NEVER modify files outside the pipeline directories listed above
- NEVER expose API keys, tokens, passwords, or secrets
- NEVER execute destructive commands (rm -rf, drop, truncate)
- NEVER modify security modules (app/security/*)
- When fixing: prefer minimal changes, explain what you changed
- Always read files before editing them
"""


_SYSTEM_PROMPT = _build_system_prompt()


def _backoff_delay(attempt: int) -> float:
    delay = min(AGENT_RETRY_BASE_DELAY * (2 ** attempt), AGENT_RETRY_MAX_DELAY)
    return delay + random.uniform(0, delay * 0.5)


def _is_retryable(error: Exception) -> bool:
    text = str(error).lower()
    if any(p in text for p in ("invalid_api_key", "authentication", "401", "403")):
        return False
    return any(p in text for p in ("timeout", "overloaded", "rate limit", "429", "500", "502", "503"))


def _get_cwd(media_slug: str | None) -> str:
    """Get safe working directory for agent tools."""
    if media_slug and media_slug in MEDIA_OUTLETS:
        cwd = str(MEDIA_OUTLETS[media_slug].project_dir)
    else:
        cwd = str(Path(__file__).resolve().parent.parent.parent)

    # Verify it's in allowed dirs
    if not any(cwd.startswith(d) for d in AGENT_ALLOWED_DIRS):
        cwd = "/tmp"
    return cwd


# ---- Async SDK calls ----

async def _async_agent(
    prompt: str,
    system_prompt: str,
    model: str,
    cwd: str,
    allowed_tools: list[str],
) -> str:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        permission_mode="bypassPermissions",
        allowed_tools=allowed_tools,
        cwd=cwd,
        max_turns=10,
    )
    parts: list[str] = []
    async for msg in sdk_query(prompt, options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    return "\n".join(parts)


async def _async_structured(
    prompt: str,
    system_prompt: str,
    model: str,
) -> str:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        permission_mode="bypassPermissions",
        allowed_tools=[],
        disallowed_tools=_ALL_BUILTIN_TOOLS,
        max_turns=1,
        cwd="/tmp",
    )
    parts: list[str] = []
    async for msg in sdk_query(prompt, options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    return "\n".join(parts)


def _run_with_retry(coro_factory, description: str) -> str:
    """Run an async SDK call with retry logic."""
    last_error: Exception | None = None

    for attempt in range(AGENT_RETRY_MAX):
        try:
            result = asyncio.run(
                asyncio.wait_for(coro_factory(), timeout=AGENT_TIMEOUT)
            )
            return result
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"{description} timed out after {AGENT_TIMEOUT}s")
        except Exception as e:
            if not _is_retryable(e):
                raise
            last_error = e

        if attempt < AGENT_RETRY_MAX - 1:
            delay = _backoff_delay(attempt)
            logger.warning("Agent retry %d/%d for %s: %s (%.1fs)",
                           attempt + 1, AGENT_RETRY_MAX - 1, description, last_error, delay)
            time.sleep(delay)

    logger.error("Agent failed after %d attempts: %s — %s", AGENT_RETRY_MAX, description, last_error)
    raise last_error  # type: ignore[misc]


# ---- Public API ----

def agent_ask(question: str, media_slug: str | None = None) -> str:
    """Ask a question about the media system. Read-only tools."""
    cwd = _get_cwd(media_slug)
    context = f" Focus on {MEDIA_OUTLETS[media_slug].name}." if media_slug else ""

    prompt = f"Answer this question about the media system.{context}\n\nQuestion: {question}"

    return _run_with_retry(
        lambda: _async_agent(prompt, _SYSTEM_PROMPT, AGENT_MODEL, cwd, TOOLS_ASK),
        f"ask: {question[:60]}",
    )


def agent_fix(media_slug: str, problem: str) -> str:
    """Diagnose and fix a pipeline issue."""
    cwd = _get_cwd(media_slug)
    cfg = MEDIA_OUTLETS[media_slug]

    prompt = (
        f"Diagnose and fix this issue in {cfg.name} pipeline.\n\n"
        f"Problem: {problem}\n\n"
        f"Steps:\n"
        f"1. Read relevant logs at {cfg.project_dir}/state/logs/pipeline.log\n"
        f"2. Check recent runs at {cfg.project_dir}/state/runs/\n"
        f"3. Identify the root cause\n"
        f"4. Apply a minimal fix\n"
        f"5. Summarize what you found and what you changed"
    )

    return _run_with_retry(
        lambda: _async_agent(prompt, _SYSTEM_PROMPT, AGENT_MODEL, cwd, TOOLS_FIX),
        f"fix: {media_slug}/{problem[:40]}",
    )


def agent_analyze(media_slug: str) -> dict:
    """Analyze content quality and pipeline health. Returns structured JSON."""
    cfg = MEDIA_OUTLETS[media_slug]

    prompt = (
        f"Analyze {cfg.name} media outlet. Read the content directory at "
        f"{cfg.project_dir}/content/ and state at {cfg.project_dir}/state/.\n\n"
        f"Return JSON with:\n"
        f"- total_articles: int\n"
        f"- articles_today: int\n"
        f"- articles_yesterday: int\n"
        f"- top_topics: list of most common topics (max 5)\n"
        f"- content_quality: 'good' | 'needs_attention' | 'poor'\n"
        f"- quality_notes: string with specific observations\n"
        f"- pipeline_health: 'healthy' | 'degraded' | 'failing'\n"
        f"- health_notes: string\n"
        f"- recommendations: list of 3 actionable suggestions"
    )

    schema = {
        "type": "object",
        "properties": {
            "total_articles": {"type": "integer"},
            "articles_today": {"type": "integer"},
            "articles_yesterday": {"type": "integer"},
            "top_topics": {"type": "array", "items": {"type": "string"}},
            "content_quality": {"type": "string", "enum": ["good", "needs_attention", "poor"]},
            "quality_notes": {"type": "string"},
            "pipeline_health": {"type": "string", "enum": ["healthy", "degraded", "failing"]},
            "health_notes": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["total_articles", "articles_today", "content_quality", "pipeline_health", "recommendations"],
    }

    raw = _run_with_retry(
        lambda: _async_structured(
            prompt + f"\n\nReturn ONLY valid JSON matching this schema:\n{json.dumps(schema, indent=2)}",
            _SYSTEM_PROMPT,
            AGENT_MODEL,
        ),
        f"analyze: {media_slug}",
    )

    # Parse JSON from response
    try:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Failed to parse analysis", "raw": raw[:500]}


def agent_improve(suggestion: str) -> str:
    """Implement a system improvement."""
    cwd = str(Path(__file__).resolve().parent.parent.parent)

    prompt = (
        f"Implement this improvement to the media management system:\n\n"
        f"Suggestion: {suggestion}\n\n"
        f"Steps:\n"
        f"1. Understand what needs to change\n"
        f"2. Read the relevant files\n"
        f"3. Make minimal, targeted changes\n"
        f"4. Summarize what you changed and why"
    )

    return _run_with_retry(
        lambda: _async_agent(prompt, _SYSTEM_PROMPT, AGENT_MODEL, cwd, TOOLS_IMPROVE),
        f"improve: {suggestion[:60]}",
    )


# ---- Async execution for bot (non-blocking) ----

def run_agent_async(
    func,
    args: tuple,
    chat_id: int,
    thinking_text: str = "⏳ Thinking...",
) -> dict:
    """Start agent call in background thread, return 'thinking' message immediately.

    When the agent finishes, the result is sent directly via TG API.
    """
    def _worker():
        try:
            result = func(*args)
            if isinstance(result, dict):
                text = _format_analysis(result)
            else:
                # Truncate very long responses for TG (4096 char limit)
                text = str(result)
                if len(text) > 4000:
                    text = text[:3950] + "\n\n... [truncated]"
            _send_tg_message(chat_id, text)
        except Exception as e:
            logger.error("Agent call failed: %s", e)
            _send_tg_message(chat_id, f"❌ Agent error: {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    return {
        "method": "sendMessage",
        "chat_id": chat_id,
        "text": thinking_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def _format_analysis(data: dict) -> str:
    """Format structured analysis as readable TG HTML."""
    if "error" in data:
        return f"❌ Analysis error: {data['error']}"

    quality_icon = {"good": "✅", "needs_attention": "⚠️", "poor": "❌"}.get(data.get("content_quality", ""), "❓")
    health_icon = {"healthy": "✅", "degraded": "⚠️", "failing": "❌"}.get(data.get("pipeline_health", ""), "❓")

    lines = [
        "<b>📊 Content Analysis</b>\n",
        f"📰 Total articles: {data.get('total_articles', '?')}",
        f"📅 Today: {data.get('articles_today', '?')} | Yesterday: {data.get('articles_yesterday', '?')}",
    ]

    topics = data.get("top_topics", [])
    if topics:
        lines.append(f"🏷 Top topics: {', '.join(topics[:5])}")

    lines.append(f"\n{quality_icon} <b>Content quality:</b> {data.get('content_quality', '?')}")
    if data.get("quality_notes"):
        lines.append(f"  {data['quality_notes']}")

    lines.append(f"\n{health_icon} <b>Pipeline health:</b> {data.get('pipeline_health', '?')}")
    if data.get("health_notes"):
        lines.append(f"  {data['health_notes']}")

    recs = data.get("recommendations", [])
    if recs:
        lines.append("\n<b>💡 Recommendations:</b>")
        for i, r in enumerate(recs[:5], 1):
            lines.append(f"  {i}. {r}")

    return "\n".join(lines)


def _send_tg_message(chat_id: int, text: str) -> None:
    """Send TG message directly (used from background threads)."""
    import httpx

    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
    try:
        httpx.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        logger.error("Failed to send TG message to %d: %s", chat_id, e)
