#!/usr/bin/env bash
# Deploy script for the ALLEN server.
# DOPPLER_TOKEN must be set in the environment (injected by GitHub Actions or manually).
set -euo pipefail
: "${DOPPLER_TOKEN:?DOPPLER_TOKEN is required — set it before running}"
cd /home/deploy/allen
doppler run -- docker compose up -d --force-recreate allen
