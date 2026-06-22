
# Deployment Architecture

## Two Separate Servers — Never Mix Them

| | Allen-I-Verse | Master Atelier |
|---|---|---|
| **Domain** | `allen.i.verse.rmasters.group` | `rmg-creator-os.rmasters.group` |
| **IP** | `74.207.230.232` | separate Linode |
| **Purpose** | ALLEN / ALLIE — AI assistant + WhatsApp | RMG Creator OS — content pipeline |
| **Stack path** | `/home/deploy/allen/` | `/opt/rmg-creator-os/control-server/` |
| **Deployed via** | `./start.sh` (manual + Doppler) | CI/CD (not a git repo on server) |
| **Doppler project** | `allen-i-verse / prd` | `rmg-creator-os` |

**Rule: anything at `allen.i.verse.*` lives on the Allen-I-Verse server. Never SSH into the Master Atelier server to fix Allen WhatsApp issues.**

---

## Allen-I-Verse Server

### Services

```
allen-allen-1      ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest
allen-postgres-1   postgres:16-alpine
allen-caddy-1      caddy:2-alpine
```

### Files at `/home/deploy/allen/`

- `docker-compose.yml` — main Allen service
- `docker-compose.caddy.yml` — Caddy reverse proxy
- `Caddyfile` — routes `allen.i.verse.rmasters.group` → `localhost:8090`
- `start.sh` — injects Doppler secrets and starts stack

### Start Command

```bash
cd ~/allen && ./start.sh
# which runs: doppler run -- docker compose up -d
```

### How to Deploy a New Image

After new code merges to `main`, GitHub Actions builds and pushes `allen:latest` to GHCR automatically. To deploy on the server:

```bash
# SSH into 74.207.230.232 as deploy
echo "YOUR_GHCR_TOKEN" | docker login ghcr.io -u PIAAR --password-stdin
docker pull ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest
cd ~/allen && ./start.sh
```

Verify:
```bash
curl -s http://localhost:8090/health | python3 -m json.tool
# "whatsapp": "ok" must appear
```

---

## docker-compose.yml (canonical reference)

```yaml
services:
  allen:
    image: ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest
    restart: unless-stopped
    environment:
      - ADMIN_API_KEY
      - ALLEN_API_KEY
      - ALLEN_VOICE_ID
      - ANTHROPIC_API_KEY
      - ANTHROPIC_MODEL
      - AUTH_ALLOWED_EMAIL
      - CAPPO_AGENT_KEY
      - CAPPO_AGENT_URL
      - CLICKUP_API_TOKEN
      - CLICKUP_TEAM_ID
      - COOKIE_SECRET
      - DATABASE_URL
      - ELEVENLABS_API_KEY
      - GDRIVE_CLIENT_ID
      - GDRIVE_CLIENT_SECRET
      - GDRIVE_REFRESH_TOKEN
      - GDRIVE_SCRIPTS_FOLDER_ID
      - GOOGLE_CLIENT_ID
      - GOOGLE_OAUTH_CLIENT_ID
      - GOOGLE_OAUTH_CLIENT_SECRET
      - NOTION_API_KEY
      - OPENAI_API_KEY
      - POSTGRES_PASSWORD
      - TWILIO_ACCOUNT_SID
      - TWILIO_AUTH_TOKEN
      - TWILIO_WHATSAPP_FROM
      - TWILIO_WHATSAPP_TO
    ports:
      - "127.0.0.1:8090:8090"
```

All env vars are bare names (no `=value`) — Doppler populates them via `doppler run --`.
**If you add a new Twilio or integration env var, it must appear in this list AND in Doppler `allen-i-verse / prd`.**

---

## Twilio WhatsApp Sandbox

- **Sandbox number:** `+1 415 523 8886`
- **Join code:** `join may-rabbit`
- **Webhook URL:** `https://allen.i.verse.rmasters.group/whatsapp/inbound` (POST)
- **Configured in:** Twilio Console → Messaging → Try it out → Send a WhatsApp message → Sandbox settings

---

## Root Cause of June 2026 Outage (for future reference)

Three compounding issues caused 3 days of downtime:

1. **Wrong image** — `docker-compose.yml` had `image: allen:latest` (local build, never updated). Fixed to `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest`.
2. **Missing Twilio env vars** — `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_TO` were in Doppler but never added to the `environment:` block in `docker-compose.yml`. Docker Compose cannot pass through vars it doesn't know about.
3. **Wrong server investigated** — `rmg-creator-os.rmasters.group` was investigated by mistake. That is a separate server. WhatsApp always belonged to the Allen-I-Verse server.

---

## Health Check

```bash
# From the server:
curl -s http://localhost:8090/health | python3 -m json.tool

# From anywhere:
curl -s https://allen.i.verse.rmasters.group/health | python3 -m json.tool
```

All checks should return `"ok"`. If `"whatsapp"` shows `"unconfigured"`, the Twilio env vars are missing from the container.
