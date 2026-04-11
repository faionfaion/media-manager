# Media Manager — Central Media Control Plane

Unified management for all Faion media pipelines. Bot: @nero_media_manager_bot. Dashboard: media-manager.faion.net.

## Structure

| Path | Purpose |
|------|---------|
| `app/api/routes.py` | FastAPI: webhook, REST API, dashboard |
| `app/bot/handlers.py` | TG bot command handlers (15 commands) |
| `app/security/injection.py` | Prompt injection detection (8 categories, 50+ patterns) |
| `app/security/validation.py` | Input validation (slug, callback, args) |
| `app/security/auth.py` | TG user ID whitelist + chat registration |
| `app/security/rate_limit.py` | Rate limiting (10 cmd/min) |
| `app/security/audit.py` | Audit logging with daily rotation (30d) |
| `app/orchestrator/runner.py` | Pipeline executor + command queue |
| `app/orchestrator/monitor.py` | Health monitor (missing articles, errors) |
| `app/orchestrator/briefing.py` | Daily morning briefing |
| `config/settings.py` | All media configs, schedules, auth |
| `scripts/local-orchestrator.sh` | Cron: queue + scheduler + monitor + briefing |
| `scripts/media-manager-bot.service` | Systemd service for bot |
| `tests/test_security.py` | 52 security tests |

## Managed Media

| Slug | Name | TG Channel | Site | Runtime |
|------|------|------------|------|---------|
| neromedia | NeroMedia | @neromedia_uk (+7 langs) | neromedia.faion.net | nero-prod |
| longlife | LongLife | @long_life_media | longlife.faion.net | faion-net |
| pashtelka | Pashtelka | @pashtelka_news | pashtelka.faion.net | faion-net |

## Bot Commands

| Command | Description | Confirmation? |
|---------|-------------|---------------|
| `/help` | Show all commands | — |
| `/status [media]` | Pipeline & channel status | — |
| `/plan [media]` | Today's editorial plan | — |
| `/generate <media>` | Full content generation | ✅ inline button |
| `/digest <media>` | Compile evening digest | — |
| `/publish <media>` | Immediate TG publish | ✅ inline button |
| `/skip <media> <slug>` | Skip an article | ✅ inline button |
| `/note <media> <text>` | Add editorial note | — |
| `/outlets` | List all managed media | — |
| `/schedule [media]` | Show cron schedules | — |
| `/logs <media> [N]` | Pipeline log tail | — |
| `/security` | Security status & stats | — |
| `/register` | Register management chat | — |
| `/unregister` | Remove management chat | — |

Free text → saved as editorial note for all outlets.

## Security (10 Guardrails)

| # | Layer | What |
|---|-------|------|
| 1 | Auth | TG user ID whitelist |
| 2 | Chat registration | Only registered chats accept commands |
| 3 | Forwarded msg block | Prevents context bypass via forwards |
| 4 | Prompt injection (8 cat) | instruction_override, role_manipulation, exfiltration, code_execution, encoding_evasion, multilang_injection, indirect_injection, homoglyph |
| 5 | Rate limiting | 10 commands/min per user |
| 6 | Input validation | Slug, callback_data, args: null bytes, path traversal, length |
| 7 | Safe prompt envelopes | Editor notes wrapped as DATA-only blocks for LLM |
| 8 | Destructive confirmation | /generate, /publish, /skip require inline button |
| 9 | Audit logging | Daily rotation, 30d retention, 10MB size guard |
| 10 | File size guards | DoS prevention on audit + queue files |

## Automation

| What | Schedule | How |
|------|----------|-----|
| Command queue | */1 * * * * | local-orchestrator.sh processes queue/ |
| Health monitor | */1 * * * * | Checks articles, runs, errors (1h cooldown) |
| Morning briefing | Once/day after 7 UTC | Yesterday stats + today plan + schedule |
| Audit rotation | On /security command | Prunes files > 30 days |

## Deployment

- **Bot**: nero-prod, systemd `media-manager-bot.service`, polling mode
- **API/Dashboard**: faion-net, systemd `media-manager.service`, port 8900
- **DNS**: media-manager.faion.net → Cloudflare (proxied) → faion-net nginx
- **Token**: `~/workspace/.env` → `MANAGER_BOT_TOKEN`

## Key Commands

```bash
# On nero-prod
sudo systemctl status media-manager-bot    # bot status
sudo journalctl -u media-manager-bot -f    # bot logs

# Manual
python main.py poll              # dev mode
python main.py process-queue     # process commands once
python main.py scheduler         # run scheduled pipelines

# Tests
python -m pytest tests/ -v       # 52 tests
```

Details: `.aidocs/INDEX.md`
