#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  printf '%s\n' 'Run python3 deploy/configure.py on the VPS first.' >&2
  exit 1
fi
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps --entrypoint python api -m unittest discover -s pilot/tests -v
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
# Provision only model files with outbound access, before starting the private runtime.
# Do not run this provisioning job concurrently with a live Ollama instance.
docker compose stop worker ollama
docker compose --profile setup run --rm model-init
docker compose up -d
printf '%s\n' 'Services started. Check docker compose ps and run the external smoke test.'
