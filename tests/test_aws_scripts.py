"""Guards for the AWS scripts (infra/aws/), no AWS needed: syntax, no SSH port, a pinned
and checksummed Compose download, and no pipeline secrets sent to the server."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

AWS = Path(__file__).resolve().parents[1] / "infra" / "aws"


@pytest.mark.parametrize("script", sorted(p.name for p in AWS.glob("*.sh")))
def test_scripts_parse(script: str) -> None:
    assert subprocess.run(["bash", "-n", str(AWS / script)], capture_output=True).returncode == 0


def test_server_opens_only_http_and_https() -> None:
    text = (AWS / "create_server.sh").read_text()

    assert set(re.findall(r"FromPort=(\d+)", text)) == {"80", "443", "5432"}  # 5432: on the RDS group
    assert "FromPort=22" not in text and "AssociatePublicIpAddress=false" in text
    assert "HttpTokens=required,HttpPutResponseHopLimit=2" in text  # containers reach the role


def test_compose_download_is_pinned_and_verified() -> None:
    text = (AWS / "user_data.sh").read_text()

    assert re.search(r"^COMPOSE_VERSION=v\d+\.\d+\.\d+$", text, re.MULTILINE)
    assert re.search(r"^COMPOSE_SHA256=[0-9a-f]{64}$", text, re.MULTILINE)
    assert "sha256sum -c" in text


def test_only_the_apps_settings_go_to_parameter_store() -> None:
    text = (AWS / "put_app_params.sh").read_text()
    names = set(re.findall(r"[A-Z][A-Z0-9_]+", " ".join(re.findall(r"^(?:PLAIN|SECRET)=\((.*)\)", text, re.MULTILINE))))

    assert names == {"RDS_HOST", "RDS_PORT", "RDS_DB", "APP_DB_USER", "APP_DB_PASSWORD", "AWS_REGION", "S3_CURATED_BUCKET"}
