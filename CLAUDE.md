# RMG AI (ALLEN / ALLIE) — Claude Orientation

> **Cross-project contracts and architecture** live in [`rmg-piaar-system`](https://github.com/RMoor-Industries-Ltd-Co/rmg-piaar-system). Read that first for the full system picture.

Isolated AI services for the RMG ecosystem. Owned by **PIAAR**. Consumed by `rmg-creator-os` gateway and directly by Rahm via WhatsApp.

## ⚠️ Two Separate Servers — Never Mix Them

| | Allen-I-Verse | Master Atelier |
|---|---|---|
| **Domain** | `allen.i.verse.rmasters.group` | `rmg-creator-os.rmasters.group` |
| **IP** | `74.207.230.232` | `45.33.96.135` |
| **Purpose** | ALLEN / ALLIE — AI assistant + WhatsApp | RMG Creator OS — content pipeline |
| **Stack path** | `/home/deploy/allen/` | `/opt/rmg-creator-os/control-server/` |
| **Doppler** | `allen-i-verse / prd` | `master-atelier / prd` |

**If WhatsApp is broken, SSH to `74.207.230.232`. Never investigate the Master Atelier server for ALLEN issues.**

## Services

| Service | Path | Purpose |
|---|---|---|
| **ALLEN** | `allen/` | Brand-voice script generation, WhatsApp bridge, daily brief, voice direction |
| **ALLIE** | `allen/allie.py` | Autonomous research agent; delegates to all ALLEN tools |

## Commands

```bash
pip install -r requirements.txt   # install deps
uvicorn allen.main:app --reload   # dev server → http://localhost:8090
```

## Git

- Active development branch: `claude/eager-bohr-w283ly`
- Never push to `main` without explicit permission.
- Never commit secrets. `.gitignore` blocks every `.env*` except `.env.example`.

## CI/CD — Build & Deploy

### Automatic (push to `main`)

`.github/workflows/publish.yml` builds and pushes the Docker image to GHCR on every push to `main`.
`.github/workflows/deploy.yml` then SSHes into the ALLEN server and force-recreates the container automatically.

Required GitHub Actions secrets:

| Secret | Value |
|---|---|
| `CONTROL_HOST` | ALLEN server IP |
| `CONTROL_USER` | `deploy` |
| `CONTROL_SSH_KEY` | ED25519 private key authorized on the server |
| `DOPPLER_TOKEN` | Doppler service token — `allen-i-verse / prd` |

### Manual deploy (emergency / off-cycle)

**Server:** `74.207.230.232` — SSH as `deploy` user. **NOT the rmg-creator-os control server.**

```bash
ssh deploy@74.207.230.232
cd ~/allen
DOPPLER_TOKEN=<token> docker compose pull allen && docker compose up -d --force-recreate allen
```

Verify: `curl -s http://localhost:8090/health | python3 -m json.tool`

### Server directory layout (clean state)

```
~/allen/          ← docker-compose.yml + start.sh; run deploys from here
~/backups/        ← backup archives
```

No source code lives on the server — the image is pulled from GHCR.
`--force-recreate allen` is always required — without it the old container stays running.

## UI

**Production URL:** `https://allen.i.verse.rmasters.group`

Served from `allen/static/console.html` via `allen/web.py`. Single HTML file — no build step.
Changes take effect after a container restart.

## Secrets

All secrets in **Doppler project `allen-i-verse`, config `prd`** (39 active). Injected at container start via `doppler run --`.
Never paste real secret values into chat or any committed file.

| Var | Notes |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API — shared AMG key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
| `ADMIN_API_KEY` | Admin endpoints + `/whatsapp/test` |
| `ALLEN_API_KEY` | Shared key for `/draft`, `/speak`, `/listen` |
| `ALLEN_VOICE_ID` | ElevenLabs voice ID for ALLEN |
| `AUTH_ALLOWED_EMAIL` | Google sign-in authorized email |
| `BASE44_API_KEY` | Base44 integration |
| `CAPPO_AGENT_KEY` / `CAPPO_AGENT_URL` | Cappo Meridian (AMG) integration |
| `CLICKUP_API_TOKEN` / `CLICKUP_TEAM_ID` | ClickUp access |
| `COOKIE_SECRET` | Session cookie encryption |
| `DATABASE_URL` | PostgreSQL connection string |
| `DEFAULT_GOOGLE_ACCOUNT` | `rahmind.consulting@rmoorind.com` |
| `ELEVENLABS_API_KEY` | TTS for voice responses |
| `FATHOM_API_KEY` / `FATHOM_WEBHOOK_SECRET` | Fathom analytics |
| `GDRIVE_CLIENT_ID` / `GDRIVE_CLIENT_SECRET` / `GDRIVE_REFRESH_TOKEN` | Legacy Drive credentials |
| `GDRIVE_SCRIPTS_FOLDER_ID` | Drive folder for script drafts |
| `GHCR_TOKEN` / `GHCR_USERNAME` | GHCR pull credentials |
| `GOOGLE_CLIENT_ID` | Google sign-in client |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Unified Google OAuth |
| `NOTION_API_KEY` | Notion access |
| `OPENAI_API_KEY` | Whisper STT for `/listen` (optional) |
| `PERPLEXITY_API_KEY` | Perplexity search integration |
| `POSTGRES_PASSWORD` | Database password |
| `SEQUENCE_API_KEY` | Sequence integration |
| `TIKTOK_CLIENT_ID_PROD` / `TIKTOK_CLIENT_SECRET_PROD` | TikTok integration |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | WhatsApp bridge |
| `TWILIO_WHATSAPP_FROM` | Sandbox: `whatsapp:+14155238886` |
| `TWILIO_WHATSAPP_TO` | Rahm's number — only authorized inbound sender |
| `YOUTUBE_API_KEY` | YouTube API access |

**If you add a new env var:** add it to `docker-compose.yml` environment block AND Doppler `allen-i-verse / prd`.

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
| `tools_calendar.py` | Google Calendar events + attendees |
| `tools_gmail.py` | Gmail read/send |
| `tools_youtube.py` | YouTube ingest (yt-dlp → Drive) |
| `tools_cappo.py` | Cappo Meridian (AMG project hub) |
| `tools_web.py` | Web browsing / search |

- **Memory**: Postgres DB — `agent_memory` table, namespaced per agent
- **WhatsApp**: Twilio REST API, `POST /whatsapp/inbound` webhook
- **Scheduler**: APScheduler cron job (`scheduler.py`) for daily brief (`report.py`)
- **Voice direction**: `emotion.py` — ElevenLabs v3 bracket tags
- **Speech**: `speech.py` (TTS out), `media.py` (STT in via Whisper)

## Key modules

| File | Purpose |
|---|---|
| `allen/main.py` | FastAPI app, mounts static files and router |
| `allen/web.py` | ALLEN I VERSE console routes (served at `/`) |
| `allen/agent.py` | ALLEN agentic loop + tool dispatch |
| `allen/allie.py` | ALLIE agent (AMG-scoped intelligence) |
| `allen/static/console.html` | Full console UI (single file, no build step) |
| `allen/config.py` | Pydantic settings (all env vars) |

## Twilio WhatsApp Sandbox

- Sandbox number: `+1 415 523 8886` / join code: `join may-rabbit`
- Webhook: `https://allen.i.verse.rmasters.group/whatsapp/inbound` (POST)
- Configure in: Twilio Console → Messaging → Try it out → Send a WhatsApp message → Sandbox settings
