#!/usr/bin/env bash
# Build and run the app in Docker on this laptop, the way the server will run it
# (Phase 6 step 5): nginx + the static frontend at http://localhost/, the API behind it
# at http://localhost/api/ (docs: /api/docs). Reads the repo's .env; only the variables
# listed in infra/docker-compose.yml reach the containers.
#
# Needs a running Docker engine. This Mac uses Colima; start it with the SSH agent unset
# (macOS's agent hangs here, which stalls Colima's start — see CLAUDE.md, Phase 6):
#   SSH_AUTH_SOCK= colima start
# Stop:  docker compose -f infra/docker-compose.yml down
# Logs:  docker compose -f infra/docker-compose.yml logs -f api
# Port:  WEB_PORT=8081 infra/docker/run_local.sh   (if port 80 is taken)
set -euo pipefail

cd "$(dirname "$0")/../.."
if [[ ! -f .env ]]; then
  echo "Missing .env at the repo root (see 'Secrets needed' in CLAUDE.md)." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Start it with:  SSH_AUTH_SOCK= colima start" >&2
  exit 1
fi

compose=(docker compose --env-file .env -f infra/docker-compose.yml)
"${compose[@]}" up --build --detach --wait "$@"
"${compose[@]}" ps
echo "App: http://localhost:${WEB_PORT:-80}/   API docs: http://localhost:${WEB_PORT:-80}/api/docs"
