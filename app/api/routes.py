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

from app.api.landing import build_landing_html
from app.api.miniapp import get_miniapp_html
from app.bot.handlers import handle_update
from app.security.auth import load_management_chats
from app.security.webapp_auth import validate_telegram_init_data
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
    if "reply_markup" in response:
        import json as _json
        payload["reply_markup"] = _json.dumps(response["reply_markup"])
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
    """Public landing page showcasing all media outlets."""
    return build_landing_html()


# -- Telegram Mini App --

def _verify_miniapp(request: Request) -> dict:
    """Verify Mini App auth from X-Telegram-Init-Data header."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Missing Telegram init data")
    try:
        return validate_telegram_init_data(init_data)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/mini-app", response_class=HTMLResponse)
async def mini_app():
    """Serve the Telegram Mini App SPA."""
    return HTMLResponse(get_miniapp_html(), headers={"X-Frame-Options": "ALLOWALL"})


@app.get("/api/mini-app/status")
async def miniapp_status(request: Request):
    """Pipeline status for Mini App."""
    _verify_miniapp(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    status = {}
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
            "tg_channel": cfg.tg_channel_username,
            "articles_today": articles_today,
            "last_run": last_run,
        }
    return JSONResponse(status)


@app.get("/api/mini-app/articles/{media_slug}")
async def miniapp_articles(media_slug: str, request: Request):
    """List today's articles for a media outlet."""
    _verify_miniapp(request)
    if media_slug not in MEDIA_OUTLETS:
        return JSONResponse({"error": "Unknown media"}, status_code=404)

    cfg = MEDIA_OUTLETS[media_slug]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    articles = []

    content_dir = cfg.project_dir / "content"
    if content_dir.exists():
        for md in sorted(content_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                text = md.read_text(encoding="utf-8")[:1000]
                if f'date: "{today}"' not in text:
                    continue
                title = ""
                atype = ""
                for line in text.split("\n"):
                    if line.startswith("title:"):
                        title = line.split('"')[1] if '"' in line else line.split(": ", 1)[1]
                    elif line.startswith("type:"):
                        atype = line.split('"')[1] if '"' in line else line.split(": ", 1)[1]
                articles.append({"title": title, "type": atype, "date": today, "slug": md.stem})
            except OSError:
                pass

    return JSONResponse({"name": cfg.name, "articles": articles})


@app.get("/api/mini-app/logs/{media_slug}")
async def miniapp_logs(media_slug: str, request: Request):
    """Pipeline log tail."""
    _verify_miniapp(request)
    if media_slug not in MEDIA_OUTLETS:
        return JSONResponse({"error": "Unknown media"}, status_code=404)

    cfg = MEDIA_OUTLETS[media_slug]
    log_file = cfg.project_dir / "state" / "logs" / "pipeline.log"
    logs = ""
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            logs = "\n".join(lines[-50:])
        except OSError:
            logs = "Error reading logs"

    return JSONResponse({"name": cfg.name, "logs": logs})


@app.post("/api/mini-app/note")
async def miniapp_note(request: Request):
    """Submit editorial note from Mini App."""
    user_data = _verify_miniapp(request)
    body = await request.json()
    media = body.get("media", "all")
    text = body.get("text", "").strip()

    if not text:
        return JSONResponse({"error": "Empty note"}, status_code=400)

    # Injection check
    from app.security.injection import detect_prompt_injection, wrap_editor_input_safely
    inj = detect_prompt_injection(text)
    if inj.risk_level in ("high", "critical"):
        return JSONResponse({"error": f"Blocked: {inj.explanation}"}, status_code=400)

    user_id = user_data["user"]["id"]
    targets = list(MEDIA_OUTLETS.keys()) if media == "all" else [media]

    for slug in targets:
        cfg = MEDIA_OUTLETS.get(slug)
        if not cfg:
            continue
        notes_file = cfg.project_dir / "state" / "editor_notes.md"
        if not notes_file.exists():
            continue
        safe = wrap_editor_input_safely(text, slug) if inj.risk_level == "medium" else text
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(f"\n- [{ts}] (user:{user_id}) {safe}\n")

    return JSONResponse({"ok": True})


@app.post("/api/mini-app/trigger/{media_slug}/{mode}")
async def miniapp_trigger(media_slug: str, mode: str, request: Request):
    """Trigger pipeline from Mini App."""
    user_data = _verify_miniapp(request)
    if media_slug not in MEDIA_OUTLETS:
        return JSONResponse({"error": "Unknown media"}, status_code=404)

    cfg = MEDIA_OUTLETS[media_slug]
    if mode not in ["generate", "publish", "digest"]:
        return JSONResponse({"error": f"Invalid mode: {mode}"}, status_code=400)

    from app.bot.handlers import _queue_command
    _queue_command(media_slug, mode, user_id=user_data["user"]["id"])
    return JSONResponse({"queued": True, "media": media_slug, "mode": mode})


@app.post("/api/mini-app/agent/ask")
async def miniapp_agent_ask(request: Request):
    """Agent ask from Mini App."""
    user_data = _verify_miniapp(request)
    body = await request.json()
    question = body.get("question", "").strip()
    media = body.get("media")
    if media == "all":
        media = None

    if not question:
        return JSONResponse({"error": "Empty question"}, status_code=400)

    from app.security.injection import detect_prompt_injection
    inj = detect_prompt_injection(question)
    if inj.risk_level in ("high", "critical"):
        return JSONResponse({"error": f"Blocked: {inj.explanation}"}, status_code=400)

    from app.security.rate_limit import check_agent_rate_limit
    if not check_agent_rate_limit(user_data["user"]["id"]):
        return JSONResponse({"error": "Agent rate limit (20/hour)"}, status_code=429)

    try:
        from app.bot.agent import agent_ask
        result = agent_ask(question, media)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/mini-app/agent/analyze/{media_slug}")
async def miniapp_agent_analyze(media_slug: str, request: Request):
    """Agent analyze from Mini App."""
    user_data = _verify_miniapp(request)
    if media_slug not in MEDIA_OUTLETS:
        return JSONResponse({"error": "Unknown media"}, status_code=404)

    from app.security.rate_limit import check_agent_rate_limit
    if not check_agent_rate_limit(user_data["user"]["id"]):
        return JSONResponse({"error": "Agent rate limit (20/hour)"}, status_code=429)

    try:
        from app.bot.agent import agent_analyze
        result = agent_analyze(media_slug)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
