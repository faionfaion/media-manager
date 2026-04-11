# Media Manager — Central Media Control Plane

Unified management for all Faion media pipelines. Bot: @nero_media_manager_bot. Dashboard: media-manager.faion.net.

## Structure

| Path | Purpose |
|------|---------|
| `app/api/routes.py` | FastAPI: webhook, REST API, Mini App routes |
| `app/api/miniapp.py` | TG Mini App SPA (HTML/CSS/JS) |
| `app/api/landing.py` | Public landing page |
| `app/bot/handlers.py` | TG bot: 20 commands, callbacks, inline buttons |
| `app/bot/agent.py` | Claude Agent SDK wrapper (4 agent functions) |
| `app/security/injection.py` | Prompt injection detection (8 categories, 55+ patterns) |
| `app/security/validation.py` | Input validation (slug, callback, args) |
| `app/security/auth.py` | TG user ID whitelist + chat registration |
| `app/security/rate_limit.py` | Rate limiting (commands: 10/min, agent: 20/hour) |
| `app/security/audit.py` | Audit logging with daily rotation (30d) |
| `app/security/webapp_auth.py` | TG Mini App initData HMAC-SHA256 auth |
| `app/orchestrator/runner.py` | Pipeline executor (background generate, sync publish/digest) |
| `app/orchestrator/monitor.py` | Health monitor + background process completion |
| `app/orchestrator/briefing.py` | Daily morning briefing |
| `config/settings.py` | All configs: media outlets, schedules, agent, security |
| `scripts/local-orchestrator.sh` | Cron: queue + scheduler + monitor + briefing |
| `tests/` | 126 tests (security, injection battery, agent, webapp auth) |

## Managed Media

| Slug | Name | TG Channel | Site | Schedule |
|------|------|------------|------|----------|
| neromedia | NeroMedia | @neromedia_uk | neromedia.faion.net | gen hourly 7-19, digest 20:00 |
| longlife | LongLife | @long_life_media | longlife.faion.net | gen 7:00, pub 9/12/15/18, digest 20:00 |
| pashtelka | Pashtelka | @pashtelka_news | pastelka.news | gen 6:00, pub 8/11/14/17, digest 19:00 |

## Bot Commands (20)

| Command | Description | Type |
|---------|-------------|------|
| `/help` | Show all commands | info |
| `/status [media]` | Pipeline & channel status | info |
| `/plan [media]` | Today's editorial plan | info |
| `/generate <media>` | Full content generation | action (confirm) |
| `/digest <media>` | Evening digest | action |
| `/publish <media>` | Immediate TG publish | action (confirm) |
| `/skip <media> <slug>` | Skip article | action (confirm) |
| `/note <media> <text>` | Editorial note | editorial |
| `/ask <question>` | AI agent: investigate | agent |
| `/analyze <media>` | AI agent: content analysis | agent |
| `/fix <media>` | AI agent: diagnose & repair | agent (confirm) |
| `/improve <text>` | AI agent: implement changes | agent (confirm) |
| `/dashboard` | Open Mini App | ui |
| `/outlets` | List managed media | info |
| `/schedule [media]` | Show cron schedules | info |
| `/logs <media> [N]` | Pipeline log tail | info |
| `/security` | Security status | info |
| `/register` | Register management chat | admin |
| `/unregister` | Remove management chat | admin |

Free text → saved as editorial note for all outlets.

## Agent SDK (Claude)

| Function | Tools | Use |
|----------|-------|-----|
| `agent_ask` | Read, Glob, Grep, Bash | Read-only investigation |
| `agent_analyze` | None (structured JSON) | Content + pipeline analysis |
| `agent_fix` | Read, Edit, Bash, Glob, Grep | Diagnose and repair |
| `agent_improve` | Read, Edit, Bash, Glob, Grep, WebSearch | Implement improvements |

System prompt has full knowledge of all 3 pipelines. CWD sandboxed. Rate: 20/hour.

## Security (10 Guardrails)

| # | Layer |
|---|-------|
| 1 | TG user ID whitelist |
| 2 | Chat registration |
| 3 | Forwarded message blocking |
| 4 | Prompt injection detection (8 categories: override, role, exfil, code, encoding, multilang UA/RU, indirect, homoglyph) |
| 5 | Rate limiting (commands 10/min, agent 20/hour) |
| 6 | Input validation (slug, callback, args, null bytes, path traversal) |
| 7 | Safe prompt envelopes (editor notes as DATA-only blocks) |
| 8 | Destructive command confirmation (inline buttons) |
| 9 | Audit logging (daily rotation, 30d retention, 10MB guard) |
| 10 | File size guards (DoS prevention) |

## Pipeline Execution

- **Generate**: background Popen (long-running, 30+ min). Lock file prevents concurrent runs. TG notification on start/completion.
- **Publish/Digest**: synchronous subprocess (2 min / 10 min timeout).
- **Dedup**: `.last_scheduled` file prevents double-fires within same minute.
- All crons replaced — media-manager is the single scheduler.

## Deployment

- **Bot**: nero-prod, systemd `media-manager-bot.service`, polling mode
- **API/Dashboard/Mini App**: faion-net, systemd `media-manager.service`, port 8900
- **DNS**: media-manager.faion.net → Cloudflare → faion-net nginx
- **Secrets**: `~/workspace/.env` (MANAGER_BOT_TOKEN, ANTHROPIC_API_KEY)

## Commands

```bash
sudo systemctl status media-manager-bot    # bot status
sudo journalctl -u media-manager-bot -f    # bot logs
python main.py poll                        # dev mode
python -m pytest tests/ -v                 # 126 tests
```
