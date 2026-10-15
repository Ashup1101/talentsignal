#!/usr/bin/env bash
# Pull-based CD, on the server (root; talentsignal-update.timer runs it every 2 minutes):
# deploy the commit CI last published, if it isn't the one running.
#
# CI pushes talentsignal-web:latest last, after every test passed on main, labelled with
# its commit — it is the release pointer. No AWS credentials live in GitHub: the server
# pulls (GitHub OIDC is blocked by this AWS Organization's policy; see CLAUDE.md).
# A commit whose deploy failed is not retried (Let's Encrypt limits failed validations);
# the next commit is. Retry by hand: rm /opt/talentsignal/LAST_FAILED.
set -euo pipefail

DIR=/opt/talentsignal
POINTER=ghcr.io/ashup1101/talentsignal-web:latest
cd "$DIR"

docker pull --quiet "$POINTER" >/dev/null
sha=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$POINTER")
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "no commit label on $POINTER: '$sha'" >&2; exit 1; }

[[ "$sha" == "$(cat DEPLOYED 2>/dev/null || true)" ]] && exit 0
[[ "$sha" == "$(cat LAST_FAILED 2>/dev/null || true)" ]] && exit 0  # waiting for a newer commit

echo "new release ${sha:0:12} (running: $(head -c 12 DEPLOYED 2>/dev/null || echo none))"
curl -fsSL --retry 3 -o deploy.sh "https://raw.githubusercontent.com/Ashup1101/talentsignal/$sha/infra/deploy/deploy.sh"
if ! bash deploy.sh "$sha"; then
  echo "$sha" > LAST_FAILED
  echo "deploy of ${sha:0:12} failed; not retried until a newer commit" >&2
  exit 1
fi
