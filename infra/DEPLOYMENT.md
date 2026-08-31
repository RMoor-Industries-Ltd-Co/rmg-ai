# ALLEN-I-Verse — Production Deployment & Environment Contract

This document makes the production environment pass-through **version-controlled** so it can
no longer drift silently on the server. It is the companion to
[`infra/docker-compose.prod.yml`](./docker-compose.prod.yml) and [`infra/start.sh`](./start.sh).

> **No secret values appear in this repo — only variable names.** All values live in Doppler
> (`allen-i-verse / prd`) and are injected at deploy time.

## Deploy model

- **Server:** dedicated ALLEN server (SSH as `deploy`), working dir `/home/deploy/allen/`.
- **Image:** `ghcr.io/rmoor-industries-ltd-co/rmg-ai/allen:latest` (built + pushed by
  `.github/workflows/publish.yml` on every push to `main`).
- **Deploy:** `.github/workflows/deploy.yml` runs `infra/start.sh` on the server, which is:
  ```bash
  doppler run -- docker compose up -d --force-recreate allen
  ```
  `doppler run` loads every `allen-i-verse/prd` secret into the **host** environment, then
  `docker compose` starts the container.

## The environment pass-through contract (the #69 fix)

`docker compose` only forwards a variable into the container if the service's `environment:`
block **names it**. `doppler run` putting a value in the host shell is *not* enough on its own.

Previously the compose file lived only at `/home/deploy/allen/docker-compose.yml` (untracked).
When new downstream variables (`CAPPO_*`, `ANPU_*`, `THOTH_*`, `VALE_*`, `CONSTANCE_*`) were
added to Doppler, that server-only file was never updated, so they never reached the container
and `GET /health?verify=true` reported every downstream agent `configured: false` (**issue #69**).

**Source of truth is now [`infra/docker-compose.prod.yml`](./docker-compose.prod.yml).** Its
`allen.environment:` block is **complete by construction** — it is generated from every field
the app reads in [`allen/config.py`](../allen/config.py), so it cannot become a partial
allow-list that silently drops a needed variable.

### Rule for future changes
Adding or renaming a setting in `allen/config.py` **must** add/rename its NAME in
`infra/docker-compose.prod.yml` (and in `.env.example`) **in the same PR**. A downstream
addition is now a **repo diff**, never a hidden server-only edit.

## Operator migration — adopt the repo-backed compose

Do this after the PR merges. Pick one path; **the safe path is recommended first.**

### Path A — Safe merge (recommended, lowest risk)
Bring only the authoritative `environment:` block onto the live file, leaving the live
`db`/`caddy`/volume definitions untouched:

1. SSH to the server: `ssh deploy@<ALLEN_SERVER>` ; `cd /home/deploy/allen`.
2. Back up the live file: `cp docker-compose.yml docker-compose.yml.bak.$(date +%F)`.
3. Open both the live `docker-compose.yml` and the repo `infra/docker-compose.prod.yml`.
   Copy the **complete `allen.environment:` list** from the repo file over the live
   `allen` service's `environment:` list (names only — no values).
4. Redeploy: `doppler run -- docker compose up -d --force-recreate allen`.
5. Validate (below).

### Path B — Full adoption (converge to one file)
Only after reconciling the RECONCILE-marked stubs:

1. In `infra/docker-compose.prod.yml`, reconcile the `db` and `caddy` service stubs
   (image tags, `POSTGRES_*` wiring vs the app's `DATABASE_URL`, the Caddyfile mount path,
   and volume names) against the values in the live `/home/deploy/allen/docker-compose.yml`.
2. Copy the reconciled file to the server as `/home/deploy/allen/docker-compose.yml`
   (keep the `.bak`).
3. Redeploy and validate as above.

From then on, the server file is a copy of the repo file; changes flow repo → server.

## Temporary server-side patch (only if visibility is needed BEFORE the PR merges)

> **Mark as temporary.** This edits the live untracked file directly and MUST be reconciled
> back to the repo-backed compose (Path A/B) afterwards, or it will drift again.

```bash
ssh deploy@<ALLEN_SERVER>
cd /home/deploy/allen
cp docker-compose.yml docker-compose.yml.bak.$(date +%F)
# Add these NAMES (no values) under the `allen` service `environment:` list, then save:
#   - CAPPO_REPORT_URL
#   - CAPPO_AGENT_KEY
#   - CONSTANCE_REPORT_URL
#   - CONSTANCE_AGENT_KEY
#   - VALE_REPORT_URL
#   - VALE_AGENT_KEY
#   - ANPU_REVIEWS_URL
#   - ANPU_REVIEWS_TOKEN
#   - ANPU_LIVENESS_URL      # optional; derives from ANPU_REVIEWS_URL if unset
#   - THOTH_STATUS_URL
#   - THOTH_STATUS_TOKEN
doppler run -- docker compose up -d --force-recreate allen
```

This changes **no Doppler values and rotates no keys** — it only tells compose to forward the
already-present host env vars into the container.

## Validation

```bash
curl -s "https://allen.i.verse.rmasters.group/health?verify=true" | python3 -m json.tool
```

Expect:
- `downstream` lists the five agents; those with URL+key in Doppler now show `configured: true`.
- `downstream_status` is **no longer globally `unconfigured`** (`ok`, or `degraded` if a
  configured agent is failing — e.g. the Vale key drift tracked separately).
- Agents with no credentials remain clearly `configured: false` (intentionally unconfigured),
  not silently absent.

## Notes

- **Do not** commit real values. `.gitignore` blocks every `.env*` except `.env.example`.
- `.env.example` documents the variable names + docs and is the human-facing contract;
  `infra/docker-compose.prod.yml` is the machine-facing pass-through contract. Keep both in
  sync with `allen/config.py`.
- Known follow-up: `.env.example` does not yet document every non-downstream setting that
  `config.py` reads (e.g. `DATABASE_URL`, `COOKIE_SECRET`, `CLICKUP_API_TOKEN`, the
  `ATELIER_*` folder IDs). The compose pass-through already covers them (generated from the
  code); expanding `.env.example` to full parity is a separate housekeeping task.
