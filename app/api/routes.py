"""FastAPI routes: webhook, API endpoints, dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.bot.handlers import handle_update
from app.security.auth import load_management_chats
from config.settings import API_SECRET, MANAGER_BOT_TOKEN, MEDIA_OUTLETS

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Media Manager",
    description="Central control plane for Faion media pipelines",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://media-manager.faion.net"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    """Load state on startup."""
    load_management_chats()
    logger.info("Media Manager started")


# -- Telegram Webhook --

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates from management bot."""
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    # Process update
    response = handle_update(body)

    # Send response if handler returned one
    if response and response.get("method") == "sendMessage":
        await _send_tg_response(response)

    return Response(status_code=200)


async def _send_tg_response(response: dict) -> None:
    """Send a Telegram API response."""
    url = f"https://api.telegram.org/bot{MANAGER_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": response["chat_id"],
        "text": response["text"],
        "parse_mode": response.get("parse_mode", "HTML"),
        "disable_web_page_preview": response.get("disable_web_page_preview", True),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("TG send failed: %s", resp.text[:200])
    except Exception as e:
        logger.error("TG send error: %s", e)


# -- Pipeline API --

@app.get("/api/status")
async def api_status(request: Request):
    """Get status of all pipelines."""
    _check_api_auth(request)

    status = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for slug, cfg in MEDIA_OUTLETS.items():
        content_dir = cfg.project_dir / "content"
        articles_today = 0
        if content_dir.exists():
            for md in content_dir.glob("*.md"):
                try:
                    text = md.read_text(encoding="utf-8")[:500]
                    if f'date: "{today}"' in text:
                        articles_today += 1
                except OSError:
                    pass

        runs_dir = cfg.project_dir / "state" / "runs"
        last_run = None
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*.json"), reverse=True)
            if run_files:
                last_run = run_files[0].stem

        status[slug] = {
            "name": cfg.name,
            "site_url": cfg.site_url,
            "tg_channel": f"@{cfg.tg_channel_username}",
            "articles_today": articles_today,
            "last_run": last_run,
        }

    return JSONResponse(status)


@app.post("/api/trigger/{media_slug}/{mode}")
async def api_trigger(media_slug: str, mode: str, request: Request):
    """Trigger a pipeline run."""
    _check_api_auth(request)

    if media_slug not in MEDIA_OUTLETS:
        return JSONResponse({"error": f"Unknown media: {media_slug}"}, status_code=404)

    cfg = MEDIA_OUTLETS[media_slug]
    valid_modes = cfg.pipeline_modes
    if mode not in valid_modes:
        return JSONResponse({"error": f"Invalid mode: {mode}. Valid: {valid_modes}"}, status_code=400)

    # Queue the command
    from app.bot.handlers import _queue_command
    _queue_command(media_slug, mode, user_id=0)

    return JSONResponse({"queued": True, "media": media_slug, "mode": mode})


@app.get("/api/health")
async def health():
    """Health check."""
    return JSONResponse({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "outlets": len(MEDIA_OUTLETS),
    })


# -- Auth helper --

def _check_api_auth(request: Request) -> None:
    """Verify API secret in Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != API_SECRET:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")


# -- Dashboard (minimal) --

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Simple dashboard landing page."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cards = []
    for slug, cfg in MEDIA_OUTLETS.items():
        cards.append(f"""
        <div class="card">
            <h2>{cfg.name}</h2>
            <p><a href="{cfg.site_url}" target="_blank">{cfg.site_url}</a></p>
            <p>TG: <a href="https://t.me/{cfg.tg_channel_username}" target="_blank">@{cfg.tg_channel_username}</a></p>
            <p>Lang: {cfg.lang if isinstance(cfg.lang, str) else ', '.join(cfg.lang)}</p>
        </div>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Media Manager — Faion Network</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, sans-serif; background: #0a0a0a; color: #e0e0e0; padding: 2rem; }}
        h1 {{ color: #fff; margin-bottom: 0.5rem; }}
        .subtitle {{ color: #888; margin-bottom: 2rem; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }}
        .card {{ background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 1.5rem; }}
        .card h2 {{ color: #4fc3f7; margin-bottom: 0.5rem; }}
        .card a {{ color: #81c784; text-decoration: none; }}
        .card a:hover {{ text-decoration: underline; }}
        .card p {{ margin: 0.3rem 0; color: #bbb; }}
        .security {{ background: #1b2a1b; border-color: #2e7d32; margin-top: 2rem; padding: 1.5rem; border-radius: 12px; border: 1px solid #2e7d32; }}
        .security h2 {{ color: #66bb6a; }}
    </style>
</head>
<body>
    <h1>Media Manager</h1>
    <p class="subtitle">Faion Network — {today}</p>
    <div class="grid">
        {''.join(cards)}
    </div>
    <div class="security">
        <h2>Security Guardrails</h2>
        <p>✅ TG user ID whitelist &nbsp; ✅ Chat registration &nbsp; ✅ Prompt injection detection (5 categories)</p>
        <p>✅ Rate limiting &nbsp; ✅ Input sanitization &nbsp; ✅ Safe prompt envelopes &nbsp; ✅ Audit logging</p>
    </div>
</body>
</html>"""
