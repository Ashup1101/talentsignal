"""Pull job postings from the JSearch API (RapidAPI) into the S3 raw zone."""

from __future__ import annotations

import argparse
import calendar
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
# Fixed order used to break ties in the rotation.
ALL_PAIRS = [(role, location) for role in SAMPLE_ROLES for location in SAMPLE_LOCATIONS]

PAGES_PER_PAIR = 3  # one API request per page
DEFAULT_MONTHLY_BUDGET = 180  # of the free plan's 200 requests/month
DEFAULT_RESERVE_REQUESTS = 20
# A scheduled run that starts late (e.g. the Mac was asleep at 22:00 UTC) still
# fetches; older logical dates are backfills and never call the API.
LATE_RUN_GRACE_DAYS = 1


class JSearchError(RuntimeError):
    """Raised when a JSearch request fails or returns an unexpected payload."""


class JSearchAccessError(JSearchError):
    """Raised on auth or quota errors, which will fail every further request too."""


class JSearchBudgetExhausted(JSearchError):
    """Raised before a request when RapidAPI reports the quota is down to the reserve."""


@dataclass
class RequestLog:
    """Counts JSearch requests made in one run and tracks RapidAPI's reported quota.

    RapidAPI reports the plan's remaining requests in the X-RateLimit-Requests-Remaining
    response header. check() runs before each request and refuses to go below the
    reserve. Retries done inside the HTTP adapter are not visible here, so `made`
    can undercount by the odd retried request; the reserve absorbs that.
    """

    reserve: int = 0
    made: int = 0
    remaining: int | None = None

    def check(self) -> None:
        """Refuse the next request if RapidAPI last reported the quota at or below the reserve.

        Raises:
            JSearchBudgetExhausted: If the last reported remaining quota <= reserve.
        """
        if self.remaining is not None and self.remaining <= self.reserve:
            raise JSearchBudgetExhausted(
                f"RapidAPI reports {self.remaining} requests left (reserve {self.reserve}); stopping"
            )

    def record(self, resp: requests.Response) -> None:
        """Count one request and remember the remaining quota RapidAPI reported.

        Args:
            resp: The response to a JSearch request.
        """
        self.made += 1
        header = (resp.headers.get("X-RateLimit-Requests-Remaining") or "").strip()
        if header.lstrip("-").isdigit():
            self.remaining = int(header)


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
    session: requests.Session,
    query: str,
    page: int,
    cursor: str | None,
    request_log: RequestLog | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    where = f"{query!r} page {page}"
    params = {"query": query} if cursor is None else {"query": query, "cursor": cursor}
    if request_log is not None:
        request_log.check()
    try:
        resp = session.get(JSEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        raise JSearchError(f"JSearch request failed for {where}: {exc}") from exc
    if request_log is not None:
        request_log.record(resp)

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


def fetch_jobs(
    role: str, location: str, num_pages: int = 3, request_log: RequestLog | None = None
) -> list[dict]:
    """Fetch raw job postings for a role in a location from JSearch's /search-v2 endpoint.

    Follows the response cursor one page (~10 jobs, one API call) at a time and
    stops early when a page is empty or no next cursor is returned.

    Args:
        role: Job title to search for, e.g. "data engineer".
        location: Location to search in, e.g. "Austin, TX".
        num_pages: Maximum number of result pages to request (one API call each).
        request_log: Optional run-wide counter; when given, every request is counted
            and refused once RapidAPI reports the quota down to the reserve.

    Returns:
        Raw job dicts exactly as JSearch returns them, across all pages.

    Raises:
        ValueError: If num_pages < 1 or RAPIDAPI_KEY is unset.
        JSearchBudgetExhausted: If request_log refuses the next request.
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
            page_jobs, cursor = _fetch_page(session, query, page, cursor, request_log)
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


@dataclass(frozen=True)
class RunPlan:
    """What one ingestion run will fetch, and the budget arithmetic behind it."""

    used_before_today: int
    used_today: int
    days_left: int
    allowance_today: int
    pairs: list[tuple[str, str]]


def plan_run(raw_keys: list[str], today: date, monthly_budget: int) -> RunPlan:
    """Choose today's role × city pairs within the calendar-month request budget.

    Budget: every raw file dated this month counts as PAGES_PER_PAIR requests, an
    upper bound computed from the S3 listing alone (no downloads). Today's allowance
    is the budget left before today spread over the days left in the month, minus
    what today already used, so rerunning the same day never spends more.

    Rotation: least recently fetched pairs first (never-fetched first); ties keep the
    fixed ALL_PAIRS order. Pairs already fetched today are not picked again.

    Args:
        raw_keys: Every key under jobs/raw/ (from s3_utils.list_keys).
        today: The fetch date (UTC).
        monthly_budget: Maximum JSearch requests per calendar month.

    Returns:
        The plan, including the pairs to fetch (possibly none).
    """
    by_slug = {(_slug(role), _slug(location)): (role, location) for role, location in ALL_PAIRS}
    last_fetched: dict[tuple[str, str], date] = {}
    files_before_today = files_today = 0

    for key in raw_keys:
        parts = key.split("/")  # jobs/raw/{role}/{location}/{date}.json
        if len(parts) != 5 or parts[:2] != ["jobs", "raw"] or not parts[4].endswith(".json"):
            continue
        try:
            fetched_on = date.fromisoformat(parts[4].removesuffix(".json"))
        except ValueError:
            continue
        if (fetched_on.year, fetched_on.month) == (today.year, today.month):
            if fetched_on == today:
                files_today += 1
            elif fetched_on < today:
                files_before_today += 1
        pair = by_slug.get((parts[2], parts[3]))
        if pair is not None and fetched_on > last_fetched.get(pair, date.min):
            last_fetched[pair] = fetched_on

    days_left = calendar.monthrange(today.year, today.month)[1] - today.day + 1
    used_before_today = files_before_today * PAGES_PER_PAIR
    used_today = files_today * PAGES_PER_PAIR
    allowance = max(0, monthly_budget - used_before_today) // days_left
    n_pairs = max(0, allowance - used_today) // PAGES_PER_PAIR
    # sorted() is stable, so pairs with the same last-fetched date keep ALL_PAIRS order.
    candidates = sorted(
        (pair for pair in ALL_PAIRS if last_fetched.get(pair) != today),
        key=lambda pair: last_fetched.get(pair, date.min),
    )
    return RunPlan(used_before_today, used_today, days_left, allowance, candidates[:n_pairs])


def save_to_s3(
    jobs: list[dict],
    role: str,
    location: str,
    run_date: date | None = None,
    api_requests: int | None = None,
) -> str:
    """Write raw jobs to the S3 raw zone, never overwriting an existing object.

    Args:
        jobs: Raw job dicts from fetch_jobs.
        role: Role the jobs were fetched for.
        location: Location the jobs were fetched for.
        run_date: Partition date; defaults to today in UTC.
        api_requests: JSearch requests spent on this pair, recorded in the envelope
            as an audit trail when given.

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

    envelope: dict[str, Any] = {
        "source": "jsearch",
        "role": role,
        "location": location,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "job_count": len(jobs),
    }
    if api_requests is not None:
        envelope["api_requests"] = api_requests
    s3_utils.upload_json(bucket, key, {**envelope, "jobs": jobs})
    return uri


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def main(argv: list[str] | None = None) -> int:
    """Fetch today's rotated role × city pairs within the JSearch request budget.

    Raw files are always dated by the actual fetch date (UTC), never by the logical
    date, so a late run can't mislabel postings.

    Args:
        argv: Arguments (defaults to sys.argv). --run-date is the run's logical date
            (Airflow passes {{ ds }}); --dry-run logs the plan without calling the API.

    Returns:
        Process exit code: 0 on success, a backfill skip, nothing to fetch, or a
        budget stop (downstream steps should still run); 1 if JSearch rejected the
        key or any pair failed.
    """
    parser = argparse.ArgumentParser(description="Fetch today's JSearch postings into the S3 raw zone.")
    parser.add_argument("--run-date", type=date.fromisoformat, help="logical date YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--dry-run", action="store_true", help="log today's plan; make no API calls or writes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    today = datetime.now(timezone.utc).date()
    run_date = args.run_date or today
    if run_date < today - timedelta(days=LATE_RUN_GRACE_DAYS):
        logger.info(
            "Run date %s is a backfill (today is %s). JSearch only returns current postings, "
            "so nothing is fetched; downstream steps rebuild from existing raw files.",
            run_date,
            today,
        )
        return 0

    bucket = s3_utils.require_env("S3_RAW_BUCKET")
    budget = _int_env("JSEARCH_MONTHLY_BUDGET", DEFAULT_MONTHLY_BUDGET)
    reserve = _int_env("JSEARCH_RESERVE_REQUESTS", DEFAULT_RESERVE_REQUESTS)
    plan = plan_run(s3_utils.list_keys(bucket, "jobs/raw/"), today, budget)
    logger.info(
        "Budget %s: %d used before today + %d today of %d; %d day(s) left → allowance %d "
        "request(s) today → %d pair(s): %s",
        f"{today:%Y-%m}",
        plan.used_before_today,
        plan.used_today,
        budget,
        plan.days_left,
        plan.allowance_today,
        len(plan.pairs),
        "; ".join(f"{role} / {location}" for role, location in plan.pairs) or "none",
    )
    if args.dry_run or not plan.pairs:
        return 0

    request_log = RequestLog(reserve=reserve)
    failures: list[str] = []
    for role, location in plan.pairs:
        made_before = request_log.made
        try:
            jobs = fetch_jobs(role, location, PAGES_PER_PAIR, request_log=request_log)
            save_to_s3(jobs, role, location, today, api_requests=request_log.made - made_before)
        except JSearchBudgetExhausted as exc:
            logger.warning("Stopping run: %s", exc)
            break
        except JSearchAccessError as exc:
            logger.error("Stopping run: %s", exc)
            return 1
        except JSearchError as exc:
            logger.error("Failed %s / %s: %s", role, location, exc)
            failures.append(f"{role} / {location}")

    remaining = "unknown" if request_log.remaining is None else request_log.remaining
    logger.info("Made %d JSearch request(s); RapidAPI reports %s remaining", request_log.made, remaining)
    if failures:
        logger.error("%d pull(s) failed: %s", len(failures), "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
