# CLAUDE.md

Guidance for Claude (and humans) working in this repo. Read this first.

## Project

**rmg-ai** — the ALLEN & ALLIE AI services powering the **ALLEN I VERSE** platform.
A FastAPI (Python) app serving the ALLEN console UI, agentic chat, voice, and ALLIE (the
AMG intelligence layer). Deployed as a Docker container on a dedicated ALLEN server.

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

`.github/workflows/publish.yml` runs on every push to `main`:
1. Builds the Docker image from `./Dockerfile`
2. Pushes two tags to GHCR:
   - `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest`
   - `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:{7-char-sha}`
3. Uses only the built-in `GITHUB_TOKEN` — no additional secrets needed

**Deploy after build is NOT automatic** — must be triggered manually on the ALLEN server (see below).

### Manual deploy (after GitHub Actions build completes)

**Server:** Dedicated ALLEN server (separate from the rmg-creator-os control server)
**Login user:** `deploy`
**Working directory:** `~/allen`

```bash
# SSH into the ALLEN server as deploy user
cd ~/allen
docker compose pull allen
docker compose up -d --force-recreate allen
```

`start.sh` in `~/allen` wraps this with Doppler secret injection:
```bash
cd ~/allen && ./start.sh
```

### Server directory layout

```
~/allen/          ← docker-compose.yml + start.sh; run deploys from here
~/allen-src/      ← source checkout (reference only)
~/backups/        ← backup archives
```

### Force-recreate vs regular restart

Always use `--force-recreate allen` when deploying a new image — without it,
`docker compose up -d` may leave the old container running if the image tag
hasn't changed (both old and new are `:latest`).

## UI

**Production URL:** `https://allen.i.verse.rmasters.group`

The ALLEN I VERSE console is served from `allen/static/console.html` via `allen/web.py`.
It is a single HTML file — no separate frontend build step. Changes to `console.html`
take effect after a container restart.

## Secrets

All runtime secrets are managed in **Doppler** (`rmg-ai` project) and injected at
container start via `doppler run --`. The authoritative variable list is in `.env.example`.

Never paste real secret values into chat or any committed file.

## Key modules

| File | Purpose |
|---|---|
| `allen/main.py` | FastAPI app, mounts static files and router |
| `allen/web.py` | ALLEN I VERSE console routes (served at `/`) |
| `allen/agent.py` | ALLEN agentic loop + tool dispatch |
| `allen/allie.py` | ALLIE agent (AMG-scoped intelligence) |
| `allen/static/console.html` | Full console UI (single file, no build step) |
| `allen/tools_gdrive.py` | Google Drive read + write tools |
| `allen/tools_calendar.py` | Google Calendar tools |
| `allen/tools_clickup.py` | ClickUp tools |
| `allen/tools_notion.py` | Notion tools |
| `allen/config.py` | Pydantic settings (all env vars) |
