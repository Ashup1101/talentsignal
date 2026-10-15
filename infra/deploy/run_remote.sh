#!/usr/bin/env bash
# Run deploy.sh for one commit on the server through SSM Run Command (no SSH), wait for it
# and show its output. The CD job uses it; from a laptop:
#   aws login --profile ts-admin
#   AWS_PROFILE=ts-admin infra/deploy/run_remote.sh i-0b5ccbfa127db4eb2 "$(git rev-parse origin/main)"
# The server fetches deploy.sh itself at that commit, so the script and the images match.
set -euo pipefail
export AWS_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""

IID=${1:?usage: run_remote.sh <instance id> <full git commit SHA>}
SHA=${2:?usage: run_remote.sh <instance id> <full git commit SHA>}
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit SHA: $SHA" >&2; exit 1; }

RAW="https://raw.githubusercontent.com/Ashup1101/talentsignal/$SHA/infra/deploy/deploy.sh"
params=$(python3 -c 'import json,sys; print(json.dumps({"executionTimeout": ["1200"], "commands": sys.argv[1:]}))' \
  "set -e" \
  "mkdir -p /opt/talentsignal" \
  "curl -fsSL --retry 3 -o /opt/talentsignal/deploy.sh $RAW" \
  "bash /opt/talentsignal/deploy.sh $SHA")
cid=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
  --comment "talentsignal deploy ${SHA:0:12}" --parameters "$params" \
  --query Command.CommandId --output text)
echo "==> SSM command $cid: deploy ${SHA:0:12} on $IID"

status=Pending
for _ in $(seq 240); do  # up to 20 minutes
  status=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$IID" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$status" in Pending|InProgress|Delayed) sleep 5 ;; *) break ;; esac
done
aws ssm get-command-invocation --command-id "$cid" --instance-id "$IID" \
  --query '[StandardOutputContent,StandardErrorContent]' --output text
echo "==> deploy: $status"
[[ "$status" == "Success" ]]
