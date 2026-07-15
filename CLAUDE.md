# CLAUDE.md

Guidance for Claude (and humans) working in this repo. Read this first.

> **Cross-project contracts and architecture** live in [`rmg-piaar-system`](https://github.com/RMoor-Industries-Ltd-Co/rmg-piaar-system). Read that first for the full system picture — it governs standing rules and cross-repo decisions for the whole PIAAR ecosystem.

## Project

**rmg-ai** — the ALLEN & ALLIE AI services powering the **ALLEN I VERSE** platform.
A FastAPI (Python) app serving the ALLEN console UI, agentic chat, voice, and ALLIE.
ALLIE is not a standalone process or a separate chat surface — she's an in-process
sub-agent ALLEN delegates to (`allen/allie.py`, invoked from `allen/agent.py`),
scoped to Rahm's BUSINESS worlds (RMG + RMI) and explicitly walled off from AMG,
which is Cappo's domain one tier further down the chain (Rahm → ALLEN → ALLIE →
Cappo). Deployed as a Docker container on a dedicated ALLEN server.

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

### Automatic deploy (push to `main`)

`.github/workflows/deploy.yml` triggers automatically after `publish.yml` succeeds:
1. SSH into the ALLEN server as `deploy` user
2. Pulls `allen:latest` from GHCR
3. Force-recreates the allen container with the new image
4. Tails the last 30 log lines to confirm startup

Required GitHub Actions secrets (set once, never change):

| Secret | Value |
|---|---|
| `CONTROL_HOST` | ALLEN server IP |
| `CONTROL_USER` | `deploy` |
| `CONTROL_SSH_KEY` | ED25519 private key authorized on the server |
| `DOPPLER_TOKEN` | Doppler service token for rmg-ai project |

### Manual deploy (emergency / off-cycle)

**Server:** Dedicated ALLEN server (NOT the rmg-creator-os control server)
**Login user:** `deploy`
**Working directory:** `~/allen`

```bash
ssh deploy@<ALLEN_SERVER_IP>
cd ~/allen
DOPPLER_TOKEN=<token> docker compose pull allen && docker compose up -d --force-recreate allen
```

### Server directory layout (clean state)

```
~/allen/          ← docker-compose.yml + start.sh; ONLY deploy artifacts here
~/backups/        ← backup archives
```

`~/allen-src/` and `~/allen/rmg-ai/` were legacy directories and have been removed.
No source code lives on the server — the image is pulled from GHCR.

### Force-recreate is always required

Always use `--force-recreate allen` — without it, `docker compose up -d` may
leave the old container running since both old and new images share the `:latest` tag.

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
| `allen/allie.py` | ALLIE — ALLEN's in-process business-ops sub-agent (RMG + RMI only; NOT AMG, that's Cappo's domain) |
| `allen/static/console.html` | Full console UI (single file, no build step) |
| `allen/tools_gdrive.py` | Google Drive read + write tools |
| `allen/tools_calendar.py` | Google Calendar tools |
| `allen/tools_clickup.py` | ClickUp tools |
| `allen/tools_notion.py` | Notion tools |
| `allen/tools_github.py` | GitHub tools — ALLEN's allen-piaar-control-bot App identity across the RMoor-Industries-Ltd-Co org |
| `allen/forms.py` | Virtual forms — dynamically-generated submit_form_* tools (schedule appointment, PIAAR initiative, business task, ...) so Claude's native required-param enforcement makes ALLEN ask instead of guess; ALLEN can define new ones himself |
| `allen/tools_market_feed.py` | Market-feed scanner (yfinance, YouTube) for "hot instrument" signals — standalone, non-agentic, unrelated to `allie.py` despite historical naming |
| `allen/feed_watch.py` | Feed-watch job — scans configured tickers, pushes signals to Thoth (axis-tekhen) |
| `allen/scheduler.py` | Background scheduler — daily WhatsApp rich morning briefing + business report + feed-watch interval job + 6-hourly agent rollup + 5-minute reminder poll |
| `allen/clock.py` | Injects the current date/time (America/New_York) into ALLEN's and ALLIE's system prompts — without it neither can compute a relative time like "remind me in 2 hours" |
| `allen/tools_anpu.py` | Pull-only tool reading AXIS/Anpu's already-cached oversight reviews (axis-tekhen's own autonomous worker) — never triggers Anpu |
| `allen/tools_thoth.py` | Pull-only tool reading AXIS/Thoth's already-cached candidate board — never triggers a rescan |
| `allen/tools_constance.py` | Delegate + pull-report tools for Constance — Connection Circle's project-owner agent; aggregate-metrics-only by design, never individual users' private data |
| `allen/tools_vale.py` | Delegate + pull-report tools for Vale — HVN Havenry's public-facing concierge; aggregate showroom-activity-only by design, never a specific visitor's conversation |
| `allen/rollup.py` | ALLEN's executive rollup — pulls Cappo/Anpu/Thoth/Constance/Vale's cached reports, synthesizes a summary, stores both in `agent_reports` so it's instant when Rahm asks, never live-computed on request |
| `allen/briefing.py` | Rich personal morning briefing (weather, calendar, ClickUp deadline audit, ranked top-5, sourced news, motivational close) — sent alongside (not instead of) `report.py`'s business-lane report |
| `allen/weather.py` | NWS (api.weather.gov) forecast lookup for the briefing, grounded to Rahm's home location (Villa Rica, GA) — no API key required |
| `allen/news.py` | RSS-based sourced headlines for the briefing (NPR general, Google News topic-search for AI/tech and finance/markets) — preserves real article links, unlike `tools_web.py`'s `web_fetch` |
| `allen/usage.py` | Usage & cost tracking — PIAAR project registry (`PIAAR_PROJECTS`, also the project-dashboard's scaffold), rate tables, the "$" console dashboard's data source |
| `allen/dashboard.py` | ALLEN·I·VERSE landing dashboard's hybrid data layer — live ClickUp milestone/subtask hierarchy per project when configured, manual `project_milestones` DB rows otherwise; never fabricates progress for an untracked project |
| `allen/tech_accounts.py` | Technology-account registry for the "$" dashboard — metered accounts cross-reference usage_log, flat-rate subscriptions show a billing-cycle countdown from a renewal day set via the console |
| `allen/brand_contracts.py` | Written brand voice performance contracts (allowed ElevenLabs v3 tags, forbidden behaviors, pacing rules, per-intensity tag density) — canonical spec in rmg-piaar-system's contracts/22; `emotion.py`'s `direct()` uses a brand's contract when one exists, else falls back to the older per-brand profile |
| `allen/config.py` | Pydantic settings (all env vars) |
