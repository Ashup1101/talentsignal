#!/usr/bin/env bash
# Deploy TalentSignal on the EC2 server, as root (the CD job runs it through SSM Run
# Command; infra/deploy/run_remote.sh does the same from a laptop):
#   deploy.sh <full git commit SHA>
# talentsignal-update.timer (update.sh) runs it for each commit CI publishes.
#
# 1. settings: /talentsignal/app/* from Parameter Store → /opt/talentsignal/.env (root only)
# 2. the compose files of that commit, from GitHub (public repo)
# 3. that commit's images from GHCR → start/replace the containers, wait until healthy
# 4. HTTPS: the first deploy gets the Let's Encrypt certificate for <ip>.sslip.io (webroot,
#    staging dry run first), then restarts nginx, which switches to TLS when it sees it
# 5. systemd: start the app at boot; check for a new release every 2 minutes (update.sh);
#    renew the certificate twice a day
# 6. remove images no container uses (the API image is ~2 GB; the disk is 20 GB)
# Never prints a setting's value.
set -euo pipefail

SHA=${1:?usage: deploy.sh <full git commit SHA>}
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit SHA: $SHA" >&2; exit 1; }

REPO=Ashup1101/talentsignal
REGISTRY=ghcr.io/ashup1101
REGION=us-east-2
CERTBOT=certbot/certbot:v5.8.0
DIR=/opt/talentsignal
log() { printf '==> %s\n' "$*"; }

mkdir -p "$DIR/letsencrypt" "$DIR/acme"
cd "$DIR"
exec 9>/var/lock/talentsignal-deploy.lock
flock -w 900 9 || { echo "another deploy is still running" >&2; exit 1; }

# The public hostname follows the instance's Elastic IP: 1.2.3.4 → 1-2-3-4.sslip.io.
imds() {
  local token
  token=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  curl -fsS -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$1"
}
TLS_HOST="$(imds public-ipv4 | tr . -).sslip.io"
log "deploying ${SHA:0:12} as $TLS_HOST"

# --- 1. Settings ---------------------------------------------------------------------------
trap 'rm -f "$DIR/.env.params" "$DIR/.env.new"' EXIT
umask 077
aws ssm get-parameters-by-path --region "$REGION" --path /talentsignal/app --with-decryption \
    --query 'Parameters[].[Name,Value]' --output text > .env.params
{
  echo "# Written by deploy.sh: settings from Parameter Store + this deploy. Do not edit."
  while IFS=$'\t' read -r name value; do
    [[ "$value" != *"'"* ]] || { echo "${name##*/} contains a single quote" >&2; exit 1; }
    echo "${name##*/}='$value'"   # single quotes: compose takes the value literally
  done < .env.params
  echo "API_IMAGE=$REGISTRY/talentsignal-api:$SHA"
  echo "WEB_IMAGE=$REGISTRY/talentsignal-web:$SHA"
  echo "WEB_BIND=0.0.0.0"
  echo "TLS_HOST=$TLS_HOST"
} > .env.new
rm -f .env.params
mv .env.new .env
log "settings: $(grep -c "^[A-Z0-9_]*='" .env) values from Parameter Store"
umask 022

# --- 2. Files of this commit: compose files + the release checker -------------------------
for f in docker-compose.yml docker-compose.prod.yml deploy/update.sh; do
  curl -fsSL --retry 3 -o "$DIR/${f##*/}.new" "https://raw.githubusercontent.com/$REPO/$SHA/infra/$f"
  mv "$DIR/${f##*/}.new" "$DIR/${f##*/}"
done
chmod 755 update.sh

# --- 3. Images and containers --------------------------------------------------------------
compose=(docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml)
log "pulling images"
"${compose[@]}" pull --quiet
"${compose[@]}" up --detach --no-build --remove-orphans --wait --wait-timeout 300
log "containers up: $("${compose[@]}" ps --format '{{.Service}} {{.Status}}' | tr '\n' ';')"

# --- 4. HTTPS ------------------------------------------------------------------------------
certbot() {
  docker run --rm -v "$DIR/letsencrypt:/etc/letsencrypt" -v "$DIR/acme:/var/www/acme" "$CERTBOT" "$@"
}
if [[ ! -f "letsencrypt/live/$TLS_HOST/fullchain.pem" ]]; then
  docker pull --quiet "$CERTBOT" >/dev/null
  # No email: Let's Encrypt no longer sends expiry mail, and renewal is automatic (step 5).
  args=(certonly --webroot -w /var/www/acme -d "$TLS_HOST" --non-interactive --agree-tos
        --register-unsafely-without-email)
  log "certificate: staging dry run"
  certbot "${args[@]}" --dry-run --quiet
  log "certificate: requesting"
  certbot "${args[@]}" --quiet
  "${compose[@]}" restart web
  "${compose[@]}" up --detach --no-build --wait --wait-timeout 120
fi
if command -v openssl >/dev/null; then
  log "certificate: $(openssl x509 -noout -enddate -in "letsencrypt/live/$TLS_HOST/fullchain.pem")"
fi

# --- 5. systemd ----------------------------------------------------------------------------
cat > /etc/systemd/system/talentsignal.service <<EOF
[Unit]
Description=TalentSignal app (Docker Compose, written by deploy.sh)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$DIR
ExecStart=/usr/bin/docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml up --detach --no-build --remove-orphans
ExecStop=/usr/bin/docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml stop
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/talentsignal-certbot.service <<EOF
[Unit]
Description=Renew the TalentSignal certificate, then reload nginx (written by deploy.sh)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm -v $DIR/letsencrypt:/etc/letsencrypt -v $DIR/acme:/var/www/acme $CERTBOT renew --quiet
ExecStart=/usr/bin/docker exec talentsignal-web-1 nginx -s reload
EOF
cat > /etc/systemd/system/talentsignal-certbot.timer <<'EOF'
[Unit]
Description=Twice-daily certificate renewal check for TalentSignal

[Timer]
OnCalendar=*-*-* 03,15:17:00
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/talentsignal-update.service <<EOF
[Unit]
Description=Deploy the release CI last published, if new (written by deploy.sh)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
ExecStart=$DIR/update.sh
TimeoutStartSec=1200
EOF
cat > /etc/systemd/system/talentsignal-update.timer <<'EOF'
[Unit]
Description=Check for a new TalentSignal release every 2 minutes

[Timer]
OnBootSec=2min
OnUnitInactiveSec=2min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --quiet talentsignal.service
systemctl enable --now --quiet talentsignal-certbot.timer talentsignal-update.timer
log "systemd: talentsignal.service enabled; renewal $(systemctl list-timers talentsignal-certbot.timer --no-legend | awk '{print "next", $1, $2, $3}')"

# --- 6. Clean up ---------------------------------------------------------------------------
docker image prune --all --force >/dev/null
log "disk: $(df -h / | awk 'NR==2 {print $3 " used, " $4 " free"}')"

# --- Check from the server itself ----------------------------------------------------------
curl -fsS --max-time 10 "https://$TLS_HOST/api/health" >/dev/null
echo "$SHA" > DEPLOYED
log "deployed ${SHA:0:12}: https://$TLS_HOST/ is healthy"
