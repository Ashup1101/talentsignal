#!/usr/bin/env bash
# Public smoke test of the live app over HTTPS, from outside AWS (the CD job runs it after
# every deploy; works from a laptop too):
#   infra/deploy/smoke_test.sh 77-113-138-96.sslip.io
# Checks: health, a valid Let's Encrypt certificate, HTTP → HTTPS redirect, HSTS, the
# pages, data from RDS, and the made-up sample resume analyzed end to end.
set -euo pipefail
cd "$(dirname "$0")/../.."

HOST=${1:?usage: smoke_test.sh <host>}
URL="https://$HOST"
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { printf '==> %-34s %s\n' "$1" "$2"; }

for _ in $(seq 12); do  # the containers may still be settling
  curl -fsS --max-time 10 -o /dev/null "$URL/api/health" && break
  sleep 5
done
ok "GET /api/health" "$(curl -fsS --max-time 10 "$URL/api/health")"  # curl verifies the certificate

# `|| true`: LibreSSL's s_client (macOS) exits 1 when its input closes, even after a good
# handshake; the content check below is what decides.
cert=$(openssl s_client -connect "$HOST:443" -servername "$HOST" </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer -enddate) || true
[[ "$cert" == *"Let's Encrypt"* ]] || fail "certificate: $cert"
ok "certificate" "$(tr '\n' ' ' <<<"$cert")"

redirect=$(curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' "http://$HOST/analyze/")
[[ "$redirect" == "301 https://$HOST/analyze/" ]] || fail "http redirect: $redirect"
ok "http:// redirect" "$redirect"

# Responses are captured before matching: `curl | grep -q` can trip pipefail (SIGPIPE).
headers=$(curl -fsSI "$URL/" | tr '[:upper:]' '[:lower:]')
[[ "$headers" == *"strict-transport-security: max-age="* ]] || fail "no HSTS header"
[[ "$(curl -fsS "$URL/")" == *"<title>TalentSignal"* ]] || fail "home page"
[[ "$(curl -fsS "$URL/analyze/")" == *"Resume Analyzer"* ]] || fail "analyzer page"
ok "pages + HSTS" "home, analyzer"

postings=$(curl -fsS "$URL/api/overview" | python3 -c 'import json,sys; print(json.load(sys.stdin)["n_postings"])')
ok "GET /api/overview (RDS)" "$postings postings"

curl -fsS -X POST "$URL/api/analyze?role=data%20engineer&level=junior" \
    -H "Content-Type: application/pdf" --data-binary @web/public/sample-resume.pdf \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert {"Python", "SQL", "Spark"} <= {s["skill"] for s in d["skills"]}, d["skills"]
assert d["postings"]["items"], "no matching postings"
label, salary = "POST /api/analyze (sample)", d["salary"]["estimate"]
skills, items = len(d["skills"]), len(d["postings"]["items"])
print(f"==> {label:<34} {skills} skills, salary ${salary:,.0f}, {items} postings")
'
echo "==> smoke test passed: $URL/"
