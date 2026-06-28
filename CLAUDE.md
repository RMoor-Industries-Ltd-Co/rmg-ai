# RMG AI (ALLEN) — Claude Orientation

> **Cross-project contracts and architecture** live in [`rmg-piaar-system`](https://github.com/RMoor-Industries-Ltd-Co/rmg-piaar-system). Read that first for the full system picture.

Isolated AI systems for the RMG ecosystem. Owned by **PIAAR** (the software sector). Consumed by `rmg-creator-os` gateway over an internal API.

## Services

| Service | Path | Purpose |
|---|---|---|
| **ALLEN** | `allen/` | Brand-voice script generation, WhatsApp bridge, daily brief, voice direction |
| **ALLIE** | `allen/allie.py` | Autonomous research agent; delegates to ALLEN tools |

## Server

- **Allen-I-Verse server**: `74.207.230.232` (SSH as `deploy`)
- **Health check**: `curl http://localhost:8090/health`
- **Container** (on control server): `control-server-allen-1`
- **Image**: `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest`

## Deploy

Push to `main` → `publish.yml` builds + pushes image to GHCR → `rmg-creator-os` deploy pulls it on next control-server deploy.

```bash
# Manual restart on control server
cd /opt/rmg-creator-os/control-server
docker compose pull allen && docker compose up -d allen

# Tail logs
docker logs control-server-allen-1 -f --tail 50
```

## Secrets

All secrets in **Doppler project `master-atelier`, config `prd`**. Key vars:

| Var | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API — shared AMG key |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | WhatsApp bridge |
| `TWILIO_WHATSAPP_FROM` / `TWILIO_WHATSAPP_TO` | Sandbox numbers |
| `DAILY_REPORT_TIME` | HH:MM local time for morning brief (TZ=America/New_York) |
| `GDRIVE_YOUTUBE_FOLDER_ID` | Drive folder for YouTube ingests |
| `ADMIN_API_KEY` | For `/whatsapp/test` and admin endpoints |

## Architecture

- **FastAPI** app in `allen/main.py`
- **Tools** split by domain: `tools_clickup.py`, `tools_notion.py`, `tools_gdrive.py`, `tools_calendar.py`, `tools_gmail.py`
- **Memory**: Postgres DB (shared with gateway) — `agent_memory` table namespaced per agent
- **WhatsApp**: Twilio REST API, `POST /whatsapp/inbound` webhook
- **Scheduler**: APScheduler cron job for daily brief
