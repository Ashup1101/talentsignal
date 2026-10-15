#!/usr/bin/env bash
# Copy the server's settings from the repo's .env to SSM Parameter Store, under
# /talentsignal/app/<NAME> (us-east-2). Values are never printed or put on a command line:
# each goes through a private temp file (aws ... --value file://).
#
# Only what the API reads goes up. The pipeline's secrets (admin RDS password, RapidAPI key,
# Databricks token) and talentsignal-dev's access keys stay off the server: on EC2 the
# instance role replaces access keys.
#   aws login --profile ts-admin
#   infra/aws/put_app_params.sh
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-ts-admin}" AWS_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""
cd "$(dirname "$0")/../.."

PLAIN=(RDS_HOST RDS_PORT RDS_DB APP_DB_USER AWS_REGION S3_CURATED_BUCKET)
SECRET=(APP_DB_PASSWORD)  # SecureString, encrypted with the account's aws/ssm key

umask 077
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

put() {  # name type
  .venv/bin/python - "$1" "$tmp" <<'EOF'
import sys
from pathlib import Path
from dotenv import dotenv_values

name, out = sys.argv[1], sys.argv[2]
value = dotenv_values(".env").get(name)
if not value:
    sys.exit(f"{name} is missing or empty in .env")
Path(out).write_text(value)
EOF
  version=$(aws ssm put-parameter --name "/talentsignal/app/$1" --type "$2" --value "file://$tmp" \
    --overwrite --query Version --output text)
  printf '==> /talentsignal/app/%s (%s, version %s)\n' "$1" "$2" "$version"
}

for name in "${PLAIN[@]}"; do put "$name" String; done
for name in "${SECRET[@]}"; do put "$name" SecureString; done
