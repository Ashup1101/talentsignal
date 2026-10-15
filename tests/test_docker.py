"""Guards for the Docker setup (infra/docker/, infra/docker-compose.yml), no Docker needed.

They check the rules a build would only reveal at run time — or never: the OpenMP
setting baked into the image, allowlist build contexts (no .env), every module the API
imports present in its image, least-privilege environment, resumes kept off nginx's disk.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "infra" / "docker"


def _allowlist(dockerfile: str) -> list[str]:
    lines = (DOCKER / f"{dockerfile}.dockerignore").read_text().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_api_image_pins_openmp_to_one_thread() -> None:
    # PyTorch + XGBoost in one process segfault with multi-threaded OpenMP (src/api/__init__.py).
    text = (DOCKER / "api.Dockerfile").read_text()

    assert re.search(r"^\s*OMP_NUM_THREADS=1\b", text, re.MULTILINE)
    assert "HF_HUB_OFFLINE=1" in text  # the embedding model is baked in, never downloaded at run time


@pytest.mark.parametrize("dockerfile", ["api.Dockerfile", "web.Dockerfile"])
def test_build_contexts_are_allowlists_without_secrets(dockerfile: str) -> None:
    patterns = _allowlist(dockerfile)

    assert patterns[0] == "*"  # everything excluded unless listed
    assert not any(".env" in p for p in patterns if p.startswith("!"))


def _local_imports(path: Path) -> set[Path]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names if a.name.startswith("src.")]
        for name in names:
            module = ROOT / Path(*name.split("."))
            for candidate in (module.with_suffix(".py"), module / "__init__.py"):
                if candidate.is_file():
                    found.add(candidate)
    return found


def test_api_image_contains_every_module_the_api_imports() -> None:
    allowed = [p[1:] for p in _allowlist("api.Dockerfile") if p.startswith("!")]
    todo, seen = set((ROOT / "src" / "api").glob("*.py")), set()
    while todo:
        path = todo.pop()
        seen.add(path)
        todo |= _local_imports(path) - seen

    missing = [
        str(rel) for rel in (PurePosixPath(p.relative_to(ROOT).as_posix()) for p in seen)
        if not any(rel.match(pattern) for pattern in allowed)
    ]
    assert not missing, f"add to api.Dockerfile.dockerignore: {missing}"


def test_api_container_gets_only_what_it_reads() -> None:
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((ROOT / "infra" / "docker-compose.yml").read_text())

    env = set(compose["services"]["api"]["environment"])
    assert {"APP_DB_USER", "APP_DB_PASSWORD", "RDS_HOST", "S3_CURATED_BUCKET"} <= env
    assert not env & {"RDS_USER", "RDS_PASSWORD", "RAPIDAPI_KEY", "DATABRICKS_TOKEN"}
    assert "ports" not in compose["services"]["api"]  # only nginx is published


def test_nginx_keeps_resumes_off_disk() -> None:
    conf = (DOCKER / "nginx" / "app.locations").read_text()
    analyze = conf[conf.index("location = /api/analyze") :]
    analyze = analyze[: analyze.index("}")]

    assert "proxy_request_buffering off;" in analyze
    assert re.search(r"client_body_buffer_size\s+6m;", analyze)
    assert re.search(r"client_max_body_size\s+6m;", analyze)


def test_https_redirect_uses_the_fixed_host_and_tls_host_is_validated() -> None:
    https = (DOCKER / "nginx" / "https.conf").read_text()
    selector = (DOCKER / "nginx" / "40-talentsignal-tls.sh").read_text()

    assert "return 301 https://__TLS_HOST__$request_uri;" in https  # never the Host header
    assert "$host" not in https
    assert "*[!a-z0-9.-]*" in selector  # TLS_HOST goes into sed and file paths
    assert re.search(r"COPY --chmod=755 infra/docker/nginx/40-talentsignal-tls\.sh", (DOCKER / "web.Dockerfile").read_text())


def test_server_compose_never_builds_and_mounts_certificates_read_only() -> None:
    yaml = pytest.importorskip("yaml")

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!reset", lambda loader, node: None)  # compose's override tag
    prod = yaml.load((ROOT / "infra" / "docker-compose.prod.yml").read_text(), Loader=Loader)

    assert all(svc["build"] is None for svc in prod["services"].values())
    assert all(v.endswith(":ro") for v in prod["services"]["web"]["volumes"])


def test_web_image_is_healthy_only_once_nginx_serves() -> None:
    # Without it `compose up --wait` returns while nginx is still starting (CI flaked on it).
    dockerfile = (DOCKER / "web.Dockerfile").read_text()

    assert re.search(r"HEALTHCHECK .*\n\s+CMD wget -q -O /dev/null http://127\.0\.0\.1/healthz", dockerfile)
    for site in ("http.conf", "https.conf"):
        assert "location = /healthz" in (DOCKER / "nginx" / site).read_text()
