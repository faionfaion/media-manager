# Media Manager — Central Media Control Plane

Unified management service for all Faion media pipelines. Domain: media-manager.faion.net.

## Structure

| Path | Purpose |
|------|---------|
| `app/` | Main application (FastAPI) |
| `app/api/` | HTTP routes, webhook, REST endpoints |
| `app/bot/` | TG management bot (command handlers) |
| `app/security/` | Auth, prompt injection detection, rate limiting, sanitization |
| `app/orchestrator/` | Pipeline runner, scheduler, command queue |
| `app/dashboard/` | Web dashboard components |
| `config/` | Settings, management chat registry |
| `tests/` | Security and integration tests |
| `logs/` | Audit log, app log |
| `queue/` | Pending pipeline commands (JSON files) |

## Managed Media

| Slug | Name | TG Channel | Site |
|------|------|------------|------|
| neromedia | NeroMedia | @neromedia_uk | neromedia.faion.net |
| longlife | LongLife | @long_life_media | longlife.faion.net |
| pashtelka | Pashtelka | @pashtelka_news | pashtelka.faion.net |

## Key Commands

```bash
python main.py serve          # Start FastAPI server
python main.py poll           # TG bot polling mode (dev)
python main.py setup-webhook  # Register TG webhook (prod)
python main.py process-queue  # Process pending commands
python main.py scheduler      # Run scheduled pipeline tasks
```

## Security Layers

1. **Auth** — TG user ID whitelist (AUTHORIZED_EDITORS)
2. **Chat registration** — only registered management chats receive commands
3. **Prompt injection detection** — 5 categories, risk scoring (safe→critical)
4. **Rate limiting** — 10 commands/minute per user
5. **Input sanitization** — strips dangerous patterns, preserves intent
6. **Safe prompt envelopes** — editor notes wrapped in DATA-only blocks for LLM
7. **Audit logging** — all commands logged to logs/audit.jsonl

## Bot Commands

| Command | Description |
|---------|-------------|
| `/status [media]` | Pipeline & channel status |
| `/plan [media]` | Today's editorial plan |
| `/publish <media>` | Trigger immediate publish |
| `/skip <media> <slug>` | Skip an article |
| `/note <media> <text>` | Add editorial note |
| `/outlets` | List all managed media |
| `/schedule [media]` | Show cron schedules |
| `/logs <media> [N]` | Last N log lines |
| `/security` | Security status & stats |
| `/register` | Register this chat |

## Bot Token

Management bot: `8578996384:AAFhkTHh_D40VdCc7em5U9taM5a-o00JzaA` (separate from publishing bots)

Details: `.aidocs/INDEX.md`
