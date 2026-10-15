#!/usr/bin/env bash
# Test the web image's two server modes with a throwaway self-signed certificate (CI's
# Docker job runs it; works on a laptop with Docker too):
#   infra/docker/test_tls.sh talentsignal-web:local
#   - TLS_HOST + certificate: HTTPS (HTTP/2, HSTS), port 80 → 301 to https://<TLS_HOST>,
#     ACME challenge still served on port 80, TLS 1.1 refused
#   - TLS_HOST, no certificate yet (first deploy): HTTP only, ACME challenge served
set -euo pipefail

IMAGE=${1:?usage: test_tls.sh <web image>}
HOST=tls.test
WORK=$(mktemp -d)
cleanup() { docker rm -f tls-https tls-first >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; docker logs tls-https 2>&1 | tail -5 >&2 || true; exit 1; }

mkdir -p "$WORK/le/live/$HOST" "$WORK/acme/.well-known/acme-challenge"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$HOST" \
  -keyout "$WORK/le/live/$HOST/privkey.pem" -out "$WORK/le/live/$HOST/fullchain.pem" 2>/dev/null
echo challenge-ok > "$WORK/acme/.well-known/acme-challenge/probe"

start() {  # name, with-certificate (yes/no), docker create args...
  local name=$1 cert=$2; shift 2
  docker create --name "$name" --add-host api:127.0.0.1 -e TLS_HOST="$HOST" "$@" "$IMAGE" >/dev/null
  docker cp "$WORK/acme/." "$name:/var/www/acme/"
  [[ "$cert" == yes ]] && docker cp "$WORK/le/." "$name:/etc/letsencrypt/"
  docker start "$name" >/dev/null
  for _ in $(seq 20); do
    [[ "$(docker logs "$name" 2>&1)" == *"start worker process"* ]] && return
    sleep 0.5
  done
  fail "$name did not start"
}
logs() { docker logs "$1" 2>&1; }  # captured first: grep -q on a pipe trips pipefail (SIGPIPE)

start tls-https yes -p 127.0.0.1:18443:443 -p 127.0.0.1:18080:80
[[ "$(logs tls-https)" == *"talentsignal: HTTPS for $HOST"* ]] || fail "HTTPS config not chosen"
H=(-sk --resolve "$HOST:18443:127.0.0.1")
[[ "$(curl "${H[@]}" -o /dev/null -w '%{http_code} %{http_version}' "https://$HOST:18443/")" == "200 2" ]] || fail "HTTPS home over HTTP/2"
[[ "$(curl "${H[@]}" -I "https://$HOST:18443/")" == *"strict-transport-security: max-age=86400"* ]] || fail "HSTS header"
[[ "$(curl "${H[@]}" "https://$HOST:18443/version.json")" == *'"commit"'* ]] || fail "version.json"
[[ "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' 'http://127.0.0.1:18080/analyze/?x=1')" \
  == "301 https://$HOST/analyze/?x=1" ]] || fail "port 80 redirect"
[[ "$(curl -s http://127.0.0.1:18080/.well-known/acme-challenge/probe)" == challenge-ok ]] || fail "ACME on port 80"
if curl "${H[@]}" --tlsv1.1 --tls-max 1.1 -o /dev/null "https://$HOST:18443/" 2>/dev/null; then fail "TLS 1.1 accepted"; fi
echo "==> HTTPS mode: HTTP/2, HSTS, redirect, ACME on 80, TLS 1.1 refused"

start tls-first no -p 127.0.0.1:18081:80
[[ "$(logs tls-first)" == *"no certificate for $HOST yet, HTTP only"* ]] || fail "HTTP fallback not chosen"
[[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/)" == 200 ]] || fail "HTTP home (first deploy)"
[[ "$(curl -s http://127.0.0.1:18081/.well-known/acme-challenge/probe)" == challenge-ok ]] || fail "ACME (first deploy)"
echo "==> first-deploy mode: HTTP only, ACME challenge served"
