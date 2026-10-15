#!/usr/bin/env bash
# Phase 6: the app server and what it needs, in us-east-2. Safe to re-run: anything that
# already exists is reused, not recreated. Run with temporary console credentials:
#   aws login --profile ts-admin
#   infra/aws/create_server.sh
#
# Creates:
#   1. security group talentsignal-web: inbound 80 + 443 from anywhere; NO port 22 (SSM only)
#   2. on the RDS security group: 5432 from talentsignal-web only (same VPC)
#   3. IAM role + instance profile talentsignal-ec2: the SSM agent's managed policy, read the
#      model and embedding objects in the curated bucket, read /talentsignal/app/* settings
#   4. EC2 t3.small, Amazon Linux 2023 x86_64, in the RDS's subnet/AZ; 20 GB gp3 encrypted;
#      IMDSv2 with hop limit 2 (containers reach the role); CPU credits "standard" (no
#      surplus charges); no automatic public IP; boot script infra/aws/user_data.sh
#   5. an Elastic IP of its own (tagged talentsignal-app), attached to the instance
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-ts-admin}" AWS_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""
cd "$(dirname "$0")/../.."

NAME=talentsignal
BUCKET=talentsignal-curated-ash
TAG_PROJECT="{Key=Project,Value=$NAME}"
log() { printf '==> %s\n' "$*"; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
RDS_HOST=$(grep -E '^RDS_HOST=' .env | cut -d= -f2-)

# --- Where: the database's VPC, security group and availability zone ---------------------
read -r RDS_ID RDS_VPC RDS_SG RDS_AZ < <(aws rds describe-db-instances \
  --query "DBInstances[?Endpoint.Address=='$RDS_HOST'] | [0].[DBInstanceIdentifier,DBSubnetGroup.VpcId,VpcSecurityGroups[0].VpcSecurityGroupId,AvailabilityZone]" \
  --output text)
[[ "$RDS_ID" != "None" ]] || { echo "No RDS instance with endpoint RDS_HOST from .env" >&2; exit 1; }
SUBNET=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$RDS_VPC" "Name=availability-zone,Values=$RDS_AZ" "Name=default-for-az,Values=true" \
  --query 'Subnets[0].SubnetId' --output text)
[[ "$SUBNET" != "None" ]] || { echo "No default subnet in $RDS_AZ of $RDS_VPC" >&2; exit 1; }
log "RDS $RDS_ID: VPC $RDS_VPC, security group $RDS_SG, $RDS_AZ → subnet $SUBNET"

# --- 1. Security group for the server ----------------------------------------------------
SG=$(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$RDS_VPC" "Name=group-name,Values=$NAME-web" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$SG" == "None" ]]; then
  SG=$(aws ec2 create-security-group --group-name "$NAME-web" --vpc-id "$RDS_VPC" \
    --description "TalentSignal app server: HTTP/HTTPS only, no SSH (SSM)" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$NAME-web},$TAG_PROJECT]" \
    --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
    "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTP (redirects to HTTPS)}]" \
    "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0,Description=HTTPS}]" >/dev/null
  log "created security group $SG ($NAME-web): 80, 443 in; no 22"
else
  log "security group $SG ($NAME-web) exists"
fi

# --- 2. RDS: allow the server's security group on 5432 -----------------------------------
if out=$(aws ec2 authorize-security-group-ingress --group-id "$RDS_SG" --ip-permissions \
    "IpProtocol=tcp,FromPort=5432,ToPort=5432,UserIdGroupPairs=[{GroupId=$SG,Description=TalentSignal app server}]" 2>&1); then
  log "RDS security group $RDS_SG: 5432 from $SG added"
elif grep -q "InvalidPermission.Duplicate" <<<"$out"; then
  log "RDS security group $RDS_SG: 5432 from $SG exists"
else
  echo "$out" >&2; exit 1
fi

# --- 3. IAM role + instance profile ------------------------------------------------------
ROLE="$NAME-ec2"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --tags "Key=Project,Value=$NAME" \
    --description "TalentSignal app server: SSM agent, read model + settings" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  log "created role $ROLE"
fi
aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name "$ROLE" --policy-name app-read --policy-document "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadModelAndEmbeddings",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": [
        "arn:aws:s3:::$BUCKET/models/salary/*",
        "arn:aws:s3:::$BUCKET/embeddings/*"
      ]
    },
    {
      "Sid": "ReadAppSettings",
      "Effect": "Allow",
      "Action": ["ssm:GetParametersByPath", "ssm:GetParameters", "ssm:GetParameter"],
      "Resource": [
        "arn:aws:ssm:$AWS_REGION:$ACCOUNT:parameter/$NAME/app",
        "arn:aws:ssm:$AWS_REGION:$ACCOUNT:parameter/$NAME/app/*"
      ]
    }
  ]
}
EOF
)"
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE" --tags "Key=Project,Value=$NAME" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  log "created instance profile $ROLE; waiting for IAM to propagate"
  sleep 15
fi
log "role $ROLE: AmazonSSMManagedInstanceCore + app-read (S3 model/embeddings, /$NAME/app/*)"

# --- 4. The instance ---------------------------------------------------------------------
IID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$NAME-app" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[0].InstanceId | [0]' --output text)
if [[ "$IID" == "None" ]]; then
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query Parameter.Value --output text)
  KEY=()
  if aws ec2 describe-key-pairs --key-names "$NAME-key" >/dev/null 2>&1; then
    KEY=(--key-name "$NAME-key")  # emergency only: port 22 stays closed
  fi
  ERR=$(mktemp); trap 'rm -f "$ERR"' EXIT
  for _ in 1 2 3 4 5; do  # a new instance profile can take a few seconds to be usable
    if IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type t3.small ${KEY[@]+"${KEY[@]}"} \
        --network-interfaces "DeviceIndex=0,SubnetId=$SUBNET,Groups=$SG,AssociatePublicIpAddress=false" \
        --iam-instance-profile "Name=$ROLE" \
        --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
        --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
        --credit-specification CpuCredits=standard \
        --user-data file://infra/aws/user_data.sh \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME-app},$TAG_PROJECT]" \
                             "ResourceType=volume,Tags=[{Key=Name,Value=$NAME-app},$TAG_PROJECT]" \
        --query 'Instances[0].InstanceId' --output text 2>"$ERR"); then
      break
    fi
    grep -q "Invalid IAM Instance Profile" "$ERR" || { cat "$ERR" >&2; exit 1; }
    sleep 10
  done
  log "launched $IID ($AMI, t3.small); waiting until it runs"
else
  log "instance $IID ($NAME-app) exists"
fi
aws ec2 wait instance-running --instance-ids "$IID"

# --- 5. The server's own Elastic IP ------------------------------------------------------
# Only an address tagged Name=talentsignal-app is ever used: the account's other Elastic IP
# is the RDS instance's public address and must stay where it is.
read -r ALLOC EIP ASSOC_IID < <(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME-app" \
  --query 'Addresses[0].[AllocationId,PublicIp,InstanceId]' --output text)
if [[ "$ALLOC" == "None" ]]; then
  read -r ALLOC EIP < <(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME-app},$TAG_PROJECT]" \
    --query '[AllocationId,PublicIp]' --output text)
  ASSOC_IID=None
  log "allocated Elastic IP $EIP ($ALLOC)"
fi
if [[ "$ASSOC_IID" != "$IID" ]]; then
  aws ec2 associate-address --allocation-id "$ALLOC" --instance-id "$IID" >/dev/null
  log "Elastic IP $EIP attached to $IID"
else
  log "Elastic IP $EIP already on $IID"
fi
log "done: instance $IID at $EIP (https host later: ${EIP//./-}.sslip.io)"
