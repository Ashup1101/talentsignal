#!/bin/bash
# First-boot script of the TalentSignal server (Amazon Linux 2023, x86_64; run once by
# cloud-init as root). Installs Docker + the Compose plugin and adds swap. The app itself
# is deployed later (deploy script + images from GHCR). Log: /var/log/talentsignal-bootstrap.log
set -euxo pipefail
exec > >(tee -a /var/log/talentsignal-bootstrap.log) 2>&1

# The instance launches without a public IP; create_server.sh attaches the Elastic IP once
# it runs. Wait for the internet (up to 10 minutes) before downloading anything.
for _ in $(seq 60); do
  curl -fsS --max-time 5 -o /dev/null https://github.com && break
  sleep 10
done

# 2 GB swap as a safety margin: the API holds ~0.8 GB of the t3.small's 2 GB of RAM.
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap defaults 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/90-swappiness.conf  # swap only under pressure
  sysctl --system >/dev/null
fi

# Docker, with container logs capped (3 × 10 MB per container) so they can't fill the disk.
dnf install -y docker
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
systemctl enable --now docker

# Docker Compose v2 plugin (not packaged for AL2023): pinned release, checksum verified.
COMPOSE_VERSION=v5.6.0
COMPOSE_SHA256=40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a
PLUGIN=/usr/local/lib/docker/cli-plugins/docker-compose
mkdir -p "$(dirname "$PLUGIN")"
curl -fsSL --retry 5 -o "$PLUGIN" \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
echo "${COMPOSE_SHA256}  ${PLUGIN}" | sha256sum -c -
chmod +x "$PLUGIN"

mkdir -p /opt/talentsignal
docker version --format 'docker {{.Server.Version}}'
docker compose version
swapon --show
echo "talentsignal bootstrap done"
