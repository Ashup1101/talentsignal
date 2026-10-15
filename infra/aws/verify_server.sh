#!/usr/bin/env bash
# Check the server end to end, through SSM Run Command (no SSH): boot script, Docker, swap,
# the instance role from inside a container (IMDSv2, 2 hops) → S3 + Parameter Store, RDS as
# app_reader through the security-group rule, and the public ports (80 open with the real
# client IP reaching the container, 22 closed). Secrets are read on the instance at run
# time; the commands stored in SSM's history contain none, and no value is printed.
#   aws login --profile ts-admin
#   infra/aws/verify_server.sh
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-ts-admin}" AWS_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""

IID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=talentsignal-app" "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
EIP=$(aws ec2 describe-addresses --filters "Name=instance-id,Values=$IID" --query 'Addresses[0].PublicIp' --output text)
echo "==> instance $IID, Elastic IP $EIP"
echo "==> SSM agent: $(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$IID" \
  --query 'InstanceInformationList[0].[PingStatus,PlatformName,PlatformVersion]' --output text)"

run() {  # description, then the shell commands to run on the instance
  local what=$1; shift
  local params cid status
  params=$(python3 -c 'import json,sys; print(json.dumps({"commands": sys.argv[1:]}))' "$@")
  cid=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
    --comment "talentsignal verify: $what" --parameters "$params" --query Command.CommandId --output text)
  for _ in $(seq 90); do
    status=$(aws ssm get-command-invocation --command-id "$cid" --instance-id "$IID" --query Status --output text 2>/dev/null || echo Pending)
    case "$status" in Pending|InProgress|Delayed) sleep 2 ;; *) break ;; esac
  done
  echo "==> $what: $status"
  aws ssm get-command-invocation --command-id "$cid" --instance-id "$IID" \
    --query '[StandardOutputContent,StandardErrorContent]' --output text | sed 's/^/    /'
  [[ "$status" == "Success" ]]
}

PROBES="public.ecr.aws/aws-cli/aws-cli:latest postgres:18-alpine nginx:1.30-alpine"
run "pull the probe images" \
  "for i in $PROBES; do docker pull -q \$i >/dev/null || exit 1; done; echo pulled"

run "host" \
  'tail -n 1 /var/log/talentsignal-bootstrap.log' \
  'docker version --format "docker {{.Server.Version}}"; docker compose version' \
  'swapon --show --noheadings; free -m | head -2' \
  'TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")' \
  'echo "role: $(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/)"'

run "settings in Parameter Store (names only)" \
  'aws ssm get-parameters-by-path --region us-east-2 --path /talentsignal/app --query "Parameters[].Name" --output text'

run "S3 from inside a container (instance role via IMDSv2)" \
  'docker run --rm -e AWS_REGION=us-east-2 public.ecr.aws/aws-cli/aws-cli:latest s3api head-object --bucket talentsignal-curated-ash --key models/salary/feature_spec.json --query "[ContentLength,LastModified]" --output text'

run "RDS as app_reader (security-group rule, SSL)" \
  'get() { aws ssm get-parameter --region us-east-2 --name "/talentsignal/app/$1" --with-decryption --query Parameter.Value --output text; }' \
  'export PGHOST=$(get RDS_HOST) PGPORT=$(get RDS_PORT) PGDATABASE=$(get RDS_DB) PGUSER=$(get APP_DB_USER) PGPASSWORD=$(get APP_DB_PASSWORD) PGSSLMODE=require' \
  'docker run --rm -e PGHOST -e PGPORT -e PGDATABASE -e PGUSER -e PGPASSWORD -e PGSSLMODE postgres:18-alpine psql -tAc "select current_user, count(*) from analytics_marts.fact_job_postings"'

run "start a throwaway nginx on port 80" \
  'docker rm -f port-probe >/dev/null 2>&1 || true; docker run -d --name port-probe -p 80:80 nginx:1.30-alpine >/dev/null && echo started'
MYIP=$(curl -s https://checkip.amazonaws.com)
echo "==> from this laptop ($MYIP): http://$EIP/ → $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$EIP/")"
if nc -z -G 5 "$EIP" 22 2>/dev/null; then echo "==> port 22: OPEN (should be closed!)"; exit 1; else echo "==> port 22: closed"; fi
run "client IP seen by the container, then remove it" \
  'docker logs port-probe 2>/dev/null | tail -n 1 | cut -d" " -f1' \
  'docker rm -f port-probe >/dev/null && echo removed'
echo "==> expected client IP: $MYIP"
run "remove the probe images" "docker image rm -f $PROBES >/dev/null && echo removed"
