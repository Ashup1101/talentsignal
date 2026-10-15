#!/bin/sh
# Picks the site config when the web container starts (the nginx image runs
# /docker-entrypoint.d/*.sh before nginx):
#   - TLS_HOST unset (laptop, CI)                       → http.conf
#   - TLS_HOST set, its certificate present (server)    → https.conf for that host
#   - TLS_HOST set, no certificate yet (first deploy)   → http.conf, which serves the ACME
#     challenge; deploy.sh gets the certificate, then restarts this container.
set -eu

site=/etc/nginx/conf.d/default.conf
if [ -n "${TLS_HOST:-}" ]; then
  case "$TLS_HOST" in
    *[!a-z0-9.-]*) echo "talentsignal: invalid TLS_HOST '$TLS_HOST'" >&2; exit 1 ;;
  esac
  if [ -f "/etc/letsencrypt/live/$TLS_HOST/fullchain.pem" ]; then
    sed "s/__TLS_HOST__/$TLS_HOST/g" /etc/nginx/talentsignal/https.conf > "$site"
    echo "talentsignal: HTTPS for $TLS_HOST"
    exit 0
  fi
  echo "talentsignal: no certificate for $TLS_HOST yet, HTTP only"
fi
cp /etc/nginx/talentsignal/http.conf "$site"
