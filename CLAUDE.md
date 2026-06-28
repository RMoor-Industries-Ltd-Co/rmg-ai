# RMG AI (ALLEN / ALLIE) — Claude Orientation

> **Cross-project contracts and architecture** live in [`rmg-piaar-system`](https://github.com/RMoor-Industries-Ltd-Co/rmg-piaar-system). Read that first for the full system picture.

Isolated AI systems for the RMG ecosystem. Owned by **PIAAR**. Consumed by `rmg-creator-os` gateway and directly by Rahm via WhatsApp.

## ⚠️ Two Separate Servers — Never Mix Them

| | Allen-I-Verse | Master Atelier |
|---|---|---|
| **Domain** | `allen.i.verse.rmasters.group` | `rmg-creator-os.rmasters.group` |
| **IP** | `74.207.230.232` | `45.33.96.135` |
| **Purpose** | ALLEN / ALLIE — AI assistant + WhatsApp | RMG Creator OS — content pipeline |
| **Stack path** | `/home/deploy/allen/` | `/opt/rmg-creator-os/control-server/` |
| **Secrets** | Doppler `allen-i-verse / prd` | Doppler `master-atelier / prd` |

**If WhatsApp is broken, SSH to `74.207.230.232`. Never investigate the Master Atelier server for Allen issues.**

## Services

| Service | Path | Purpose |
|---|---|---|
| **ALLEN** | `allen/` | Brand-voice script generation, WhatsApp bridge, daily brief, voice direction |
| **ALLIE** | `allen/allie.py` + `allie/` | Autonomous research agent; delegates to all ALLEN tools |

## Allen-I-Verse Server

- **SSH**: `ssh deploy@74.207.230.232`
- **Stack**: `/home/deploy/allen/` — `docker-compose.yml` + `start.sh`
- **Containers**: `allen-allen-1`, `allen-postgres-1`, `allen-caddy-1`
- **Health**: `curl -s https://allen.i.verse.rmasters.group/health | python3 -m json.tool`
- **Image**: `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest`

## Deploy

Push to `main` → GitHub Actions builds and pushes image to GHCR. To deploy on the server:

```bash
# SSH into Allen-I-Verse server
ssh deploy@74.207.230.232
docker pull ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest
cd ~/allen && ./start.sh
# ./start.sh runs: doppler run -- docker compose up -d
```

Verify with: `curl -s http://localhost:8090/health | python3 -m json.tool` — `"whatsapp": "ok"` must appear.

## Secrets

All secrets in **Doppler project `allen-i-verse`, config `prd`**. Key vars:

| Var | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API — shared AMG key |
| `ANTHROPIC_MODEL` | Default: `claude-3-5-sonnet-latest` |
| `ELEVENLABS_API_KEY` | TTS for voice responses |
| `ALLEN_VOICE_ID` | ElevenLabs voice ID for ALLEN |
| `OPENAI_API_KEY` | Whisper STT for `/listen` (optional) |
| `GOOGLE_OAUTH_CLIENT_ID/SECRET` | Unified Google OAuth (Calendar, Gmail, Drive) |
| `DEFAULT_GOOGLE_ACCOUNT` | `rahmind.consulting@rmoorind.com` |
| `GDRIVE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Legacy Drive credentials for docs/youtube ingest |
| `GDRIVE_SCRIPTS_FOLDER_ID` | Drive folder for script drafts |
| `GDRIVE_YOUTUBE_FOLDER_ID` | Drive folder for YouTube ingests |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | WhatsApp bridge |
| `TWILIO_WHATSAPP_FROM` | Sandbox: `whatsapp:+14155238886` |
| `TWILIO_WHATSAPP_TO` | Rahm's number — only authorized inbound sender |
| `DAILY_REPORT_TIME` | HH:MM for morning brief (container TZ = America/New_York) |
| `CLICKUP_API_TOKEN` / `CLICKUP_TEAM_ID` | ClickUp access |
| `NOTION_API_KEY` | Notion access |
| `CAPPO_AGENT_URL` / `CAPPO_AGENT_KEY` | Cappo Meridian (AMG) integration |
| `ADMIN_API_KEY` | For `/whatsapp/test` and admin endpoints |

**If you add a new env var, add it to `docker-compose.yml` environment block AND Doppler `allen-i-verse / prd`.**

## Google Multi-Account

ALLEN supports 7 of Rahm's Google accounts. Authorize each at:
`https://allen.i.verse.rmasters.group/oauth/google/start?account=EMAIL`

Accounts: `rmoorind@rmoorind.com`, `rahmind.consulting@rmoorind.com` (default), `rmoorindustries@gmail.com`, `amg@apex-meridian-group.com`, `rahm@rmasters.group`, `kingrahjah@gmail.com`, `rmooreking@gmail.com`.

## Architecture

- **FastAPI** app in `allen/main.py`
- **Tools** split by domain:

| File | Domain |
|---|---|
| `tools_clickup.py` | ClickUp tasks/lists/spaces |
| `tools_notion.py` | Notion pages/databases |
| `tools_gdrive.py` | Google Drive CRUD (read + write) |
| `tools_calendar.py` | Google Calendar events |
| `tools_gmail.py` | Gmail read/send |
| `tools_youtube.py` | YouTube ingest (yt-dlp → Drive) |
| `tools_cappo.py` | Cappo Meridian (AMG project hub) |
| `tools_web.py` | Web browsing / search |

- **Memory**: Postgres DB — `agent_memory` table, namespaced per agent
- **WhatsApp**: Twilio REST API, `POST /whatsapp/inbound` webhook
- **Scheduler**: APScheduler cron job (`scheduler.py`) for daily brief (`report.py`)
- **Voice direction**: `emotion.py` — ElevenLabs v3 bracket tags
- **Speech**: `speech.py` (TTS out), `media.py` (STT in via Whisper)

## Twilio WhatsApp Sandbox

- Sandbox number: `+1 415 523 8886` / join code: `join may-rabbit`
- Webhook: `https://allen.i.verse.rmasters.group/whatsapp/inbound` (POST)
- Configure in: Twilio Console → Messaging → Try it out → Send a WhatsApp message → Sandbox settings
