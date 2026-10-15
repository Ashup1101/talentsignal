"""Guards for the deploy scripts (infra/deploy/), no server needed: they refuse anything but
a full commit SHA before touching anything, and the release pointer / failure rules hold."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "infra" / "deploy"


@pytest.mark.parametrize(("script", "args"), [("deploy.sh", ["main"]), ("run_remote.sh", ["i-0123", "abc123"])])
def test_scripts_refuse_anything_but_a_full_commit_sha(script: str, args: list[str]) -> None:
    result = subprocess.run(["bash", str(DEPLOY / script), *args], capture_output=True, text=True)

    assert result.returncode == 1 and "not a full commit SHA" in result.stderr


@pytest.mark.parametrize("script", sorted(p.name for p in DEPLOY.glob("*.sh")))
def test_scripts_parse(script: str) -> None:
    assert subprocess.run(["bash", "-n", str(DEPLOY / script)], capture_output=True).returncode == 0


def test_deploy_records_success_only_after_the_health_check() -> None:
    text = (DEPLOY / "deploy.sh").read_text()

    assert text.index('/api/health"') < text.index('echo "$SHA" > DEPLOYED')
    assert "--register-unsafely-without-email" in text  # no personal email sent to Let's Encrypt
    assert "--dry-run" in text  # staging first: failed validations count against real limits


def test_update_follows_the_web_pointer_and_skips_a_failed_commit() -> None:
    text = (DEPLOY / "update.sh").read_text()

    assert "POINTER=ghcr.io/ashup1101/talentsignal-web:latest" in text
    assert "org.opencontainers.image.revision" in text
    assert "LAST_FAILED" in text
