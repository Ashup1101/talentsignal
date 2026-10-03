"""Pull job postings from the JSearch API (RapidAPI) into the S3 raw zone."""

from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.ingestion import s3_utils

logger = logging.getLogger(__name__)

JSEARCH_HOST = "jsearch.p.rapidapi.com"
# /search was retired in favour of the cursor-paginated /search-v2.
JSEARCH_URL = f"https://{JSEARCH_HOST}/search-v2"
REQUEST_TIMEOUT_S = 30

SAMPLE_ROLES = [
    "data engineer",
    "data scientist",
    "machine learning engineer",
    "data analyst",
    "software engineer",
]
SAMPLE_LOCATIONS = [
    "New York, NY",
    "San Francisco, CA",
    "Seattle, WA",
    "Austin, TX",
    "Chicago, IL",
]


class JSearchError(RuntimeError):
    """Raised when a JSearch request fails or returns an unexpected payload."""


class JSearchAccessError(JSearchError):
    """Raised on auth or quota errors, which will fail every further request too."""


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {"X-RapidAPI-Key": s3_utils.require_env("RAPIDAPI_KEY"), "X-RapidAPI-Host": JSEARCH_HOST}
    )
    return session


def _fetch_page(
    session: requests.Session, query: str, page: int, cursor: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    where = f"{query!r} page {page}"
    params = {"query": query} if cursor is None else {"query": query, "cursor": cursor}
    try:
        resp = session.get(JSEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        raise JSearchError(f"JSearch request failed for {where}: {exc}") from exc

    if resp.status_code in (401, 403):
        raise JSearchAccessError(
            f"JSearch rejected the request (HTTP {resp.status_code}). Check RAPIDAPI_KEY and "
            f"that the key is subscribed to JSearch on RapidAPI. Response: {resp.text[:200]}"
        )
    if resp.status_code == 429:
        raise JSearchAccessError(
            f"JSearch rate limit or plan quota exceeded (HTTP 429) on {where}. Response: {resp.text[:200]}"
        )
    if not resp.ok:
        raise JSearchError(f"JSearch returned HTTP {resp.status_code} for {where}: {resp.text[:200]}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise JSearchError(f"JSearch returned non-JSON for {where}: {resp.text[:200]}") from exc
    # Expected shape: {"status": "OK", "data": {"jobs": [...], "cursor": "<next page token>"}}
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or body.get("status") != "OK" or not isinstance(data.get("jobs"), list):
        summary = sorted(body) if isinstance(body, dict) else type(body).__name__
        status = body.get("status") if isinstance(body, dict) else None
        raise JSearchError(f"Unexpected JSearch payload for {where}: status={status!r}, keys={summary}")
    return data["jobs"], data.get("cursor") or None


def fetch_jobs(role: str, location: str, num_pages: int = 3) -> list[dict]:
    """Fetch raw job postings for a role in a location from JSearch's /search-v2 endpoint.

    Follows the response cursor one page (~10 jobs, one API call) at a time and
    stops early when a page is empty or no next cursor is returned.

    Args:
        role: Job title to search for, e.g. "data engineer".
        location: Location to search in, e.g. "Austin, TX".
        num_pages: Maximum number of result pages to request (one API call each).

    Returns:
        Raw job dicts exactly as JSearch returns them, across all pages.

    Raises:
        ValueError: If num_pages < 1 or RAPIDAPI_KEY is unset.
        JSearchAccessError: On auth (401/403) or quota (429) errors.
        JSearchError: On any other failed request or unexpected payload.
    """
    if num_pages < 1:
        raise ValueError(f"num_pages must be at least 1, got {num_pages}")

    query = f"{role} in {location}"
    jobs: list[dict] = []
    cursor: str | None = None
    with _session() as session:
        for page in range(1, num_pages + 1):
            page_jobs, cursor = _fetch_page(session, query, page, cursor)
            jobs.extend(page_jobs)
            if not page_jobs or cursor is None:
                logger.info("No more results after page %d for %r", page, query)
                break

    logger.info("Fetched %d jobs for %r", len(jobs), query)
    return jobs


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    if not slug:
        raise ValueError(f"Cannot build an S3 key segment from {text!r}")
    return slug


def raw_key(role: str, location: str, run_date: date | None = None) -> str:
    """Build the raw-zone S3 key for one role + location + date.

    Args:
        role: Job title, e.g. "Data Engineer".
        location: Location, e.g. "New York, NY".
        run_date: Partition date; defaults to today in UTC.

    Returns:
        A key like "jobs/raw/data_engineer/new_york_ny/2026-10-02.json".
    """
    run_date = run_date or datetime.now(timezone.utc).date()
    return f"jobs/raw/{_slug(role)}/{_slug(location)}/{run_date.isoformat()}.json"


def save_to_s3(jobs: list[dict], role: str, location: str, run_date: date | None = None) -> str:
    """Write raw jobs to the S3 raw zone, never overwriting an existing object.

    Args:
        jobs: Raw job dicts from fetch_jobs.
        role: Role the jobs were fetched for.
        location: Location the jobs were fetched for.
        run_date: Partition date; defaults to today in UTC. Airflow passes its logical date.

    Returns:
        The object's s3:// URI, whether newly written or already present.

    Raises:
        ValueError: If S3_RAW_BUCKET or an AWS env var is unset.
        S3OperationError: If an S3 call fails.
    """
    bucket = s3_utils.require_env("S3_RAW_BUCKET")
    key = raw_key(role, location, run_date)
    uri = f"s3://{bucket}/{key}"

    if s3_utils.key_exists(bucket, key):
        logger.info("%s already exists; leaving it unchanged", uri)
        return uri
    if not jobs:
        logger.warning("Saving 0 jobs for %r in %r to %s", role, location, uri)

    s3_utils.upload_json(
        bucket,
        key,
        {
            "source": "jsearch",
            "role": role,
            "location": location,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "job_count": len(jobs),
            "jobs": jobs,
        },
    )
    return uri


def main() -> int:
    """Pull every sample role × location that has no raw file for today yet.

    Returns:
        Process exit code: 0 if every pull succeeded or was already present, 1 otherwise.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bucket = s3_utils.require_env("S3_RAW_BUCKET")
    failures: list[str] = []

    for role in SAMPLE_ROLES:
        for location in SAMPLE_LOCATIONS:
            # Check before fetching so reruns don't spend API quota on data we already have.
            if s3_utils.key_exists(bucket, raw_key(role, location)):
                logger.info("Skipping %s / %s: already landed today", role, location)
                continue
            try:
                save_to_s3(fetch_jobs(role, location), role, location)
            except JSearchAccessError as exc:
                logger.error("Stopping run: %s", exc)
                return 1
            except JSearchError as exc:
                logger.error("Failed %s / %s: %s", role, location, exc)
                failures.append(f"{role} / {location}")

    if failures:
        logger.error("%d pull(s) failed: %s", len(failures), "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
