"""Tests for src.ingestion.

S3 calls are stubbed with botocore's Stubber (s3_utils) or an in-memory fake
(fetch modules); HTTP calls are intercepted with `responses`.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timezone

import pytest
import responses
from botocore.stub import Stubber
from openpyxl import Workbook

from src.ingestion import fetch_bls, fetch_jobs, s3_utils

BUCKET = "test-bucket"


@pytest.fixture
def s3_stub(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    s3_utils._client.cache_clear()
    with Stubber(s3_utils._client()) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()
    s3_utils._client.cache_clear()


def test_upload_json_writes_serialized_body(s3_stub: Stubber) -> None:
    data = {"role": "data engineer", "city": "São Paulo"}
    s3_stub.add_response(
        "put_object",
        {},
        expected_params={
            "Bucket": BUCKET,
            "Key": "jobs/raw/x.json",
            "Body": json.dumps(data, ensure_ascii=False).encode("utf-8"),
            "ContentType": "application/json",
        },
    )
    s3_utils.upload_json(BUCKET, "jobs/raw/x.json", data)


def test_upload_json_rejects_unserializable_data(s3_stub: Stubber) -> None:
    with pytest.raises(ValueError, match="not JSON-serializable"):
        s3_utils.upload_json(BUCKET, "k.json", {"bad": object()})


def test_upload_json_wraps_client_error(s3_stub: Stubber) -> None:
    s3_stub.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(s3_utils.S3OperationError, match="Failed to upload s3://test-bucket/k.json"):
        s3_utils.upload_json(BUCKET, "k.json", {"a": 1})


def test_key_exists_true(s3_stub: Stubber) -> None:
    s3_stub.add_response("head_object", {}, expected_params={"Bucket": BUCKET, "Key": "k.json"})
    assert s3_utils.key_exists(BUCKET, "k.json") is True


def test_key_exists_false_on_404(s3_stub: Stubber) -> None:
    s3_stub.add_client_error("head_object", service_error_code="404", http_status_code=404)
    assert s3_utils.key_exists(BUCKET, "k.json") is False


def test_key_exists_raises_on_403(s3_stub: Stubber) -> None:
    s3_stub.add_client_error("head_object", service_error_code="403", http_status_code=403)
    with pytest.raises(s3_utils.S3OperationError, match="s3:ListBucket"):
        s3_utils.key_exists(BUCKET, "k.json")


def test_list_keys_follows_pagination(s3_stub: Stubber) -> None:
    s3_stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "jobs/raw/a.json"}], "IsTruncated": True, "NextContinuationToken": "t1"},
        expected_params={"Bucket": BUCKET, "Prefix": "jobs/raw/"},
    )
    s3_stub.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": "jobs/raw/b.json"}], "IsTruncated": False},
        expected_params={"Bucket": BUCKET, "Prefix": "jobs/raw/", "ContinuationToken": "t1"},
    )
    assert s3_utils.list_keys(BUCKET, "jobs/raw/") == ["jobs/raw/a.json", "jobs/raw/b.json"]


def test_list_keys_empty_prefix(s3_stub: Stubber) -> None:
    s3_stub.add_response("list_objects_v2", {"IsTruncated": False, "KeyCount": 0})
    assert s3_utils.list_keys(BUCKET, "nothing/") == []


def test_missing_aws_env_var_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    s3_utils._client.cache_clear()
    with pytest.raises(ValueError, match="AWS_ACCESS_KEY_ID is not set"):
        s3_utils.key_exists(BUCKET, "k.json")
    s3_utils._client.cache_clear()


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """Replace S3 writes/existence checks with an in-memory {key: body} store."""
    monkeypatch.setenv("S3_RAW_BUCKET", BUCKET)
    store: dict[str, dict] = {}
    monkeypatch.setattr(s3_utils, "key_exists", lambda bucket, key: key in store)
    monkeypatch.setattr(s3_utils, "upload_json", lambda bucket, key, data: store.__setitem__(key, data))
    return store


# --- fetch_jobs ---------------------------------------------------------------


@pytest.fixture
def jsearch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")


def _jsearch_page(*job_ids: str, cursor: str | None = "next") -> dict:
    """Mirror the /search-v2 response shape: jobs and the next-page cursor sit under "data"."""
    data: dict = {"jobs": [{"job_id": j} for j in job_ids]}
    if cursor is not None:
        data["cursor"] = cursor
    return {"status": "OK", "request_id": "req-1", "parameters": {}, "data": data}


@responses.activate
def test_fetch_jobs_follows_cursor_until_empty_page(jsearch_env: None) -> None:
    responses.get(fetch_jobs.JSEARCH_URL, json=_jsearch_page("a", "b", cursor="c1"))
    responses.get(fetch_jobs.JSEARCH_URL, json=_jsearch_page("c", cursor="c2"))
    responses.get(fetch_jobs.JSEARCH_URL, json=_jsearch_page(cursor="c3"))

    jobs = fetch_jobs.fetch_jobs("data engineer", "Austin, TX", num_pages=5)

    assert [j["job_id"] for j in jobs] == ["a", "b", "c"]
    assert len(responses.calls) == 3
    first, second = responses.calls[0].request, responses.calls[1].request
    assert first.headers["X-RapidAPI-Key"] == "test-key"
    assert first.params == {"query": "data engineer in Austin, TX"}
    assert second.params == {"query": "data engineer in Austin, TX", "cursor": "c1"}


@responses.activate
def test_fetch_jobs_stops_when_no_cursor_returned(jsearch_env: None) -> None:
    responses.get(fetch_jobs.JSEARCH_URL, json=_jsearch_page("a", "b", cursor=None))
    assert len(fetch_jobs.fetch_jobs("data engineer", "Austin, TX", num_pages=3)) == 2
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_jobs_stops_at_num_pages(jsearch_env: None) -> None:
    responses.get(fetch_jobs.JSEARCH_URL, json=_jsearch_page("a"))
    assert len(fetch_jobs.fetch_jobs("data engineer", "Austin, TX", num_pages=2)) == 2
    assert len(responses.calls) == 2


@responses.activate
def test_fetch_jobs_raises_access_error_on_403(jsearch_env: None) -> None:
    responses.get(fetch_jobs.JSEARCH_URL, status=403, json={"message": "You are not subscribed to this API."})
    with pytest.raises(fetch_jobs.JSearchAccessError, match="RAPIDAPI_KEY"):
        fetch_jobs.fetch_jobs("data engineer", "Austin, TX")


@responses.activate
def test_fetch_jobs_rejects_unexpected_payload(jsearch_env: None) -> None:
    responses.get(fetch_jobs.JSEARCH_URL, json={"status": "ERROR", "error": {"message": "bad query"}})
    with pytest.raises(fetch_jobs.JSearchError, match="status='ERROR'"):
        fetch_jobs.fetch_jobs("data engineer", "Austin, TX")


def test_fetch_jobs_requires_rapidapi_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    with pytest.raises(ValueError, match="RAPIDAPI_KEY is not set"):
        fetch_jobs.fetch_jobs("data engineer", "Austin, TX")


def test_raw_key_slugs_role_and_location() -> None:
    key = fetch_jobs.raw_key("Machine Learning Engineer", "New York, NY", date(2026, 10, 2))
    assert key == "jobs/raw/machine_learning_engineer/new_york_ny/2026-10-02.json"


def test_save_jobs_writes_envelope(fake_s3: dict[str, dict]) -> None:
    uri = fetch_jobs.save_to_s3([{"job_id": "a"}], "data engineer", "Austin, TX", date(2026, 10, 2))

    key = "jobs/raw/data_engineer/austin_tx/2026-10-02.json"
    assert uri == f"s3://{BUCKET}/{key}"
    body = fake_s3[key]
    assert body["jobs"] == [{"job_id": "a"}]
    assert (body["source"], body["role"], body["location"], body["job_count"]) == (
        "jsearch",
        "data engineer",
        "Austin, TX",
        1,
    )


def test_save_jobs_never_overwrites(fake_s3: dict[str, dict]) -> None:
    key = "jobs/raw/data_engineer/austin_tx/2026-10-02.json"
    fake_s3[key] = {"jobs": ["original"]}

    uri = fetch_jobs.save_to_s3([{"job_id": "new"}], "data engineer", "Austin, TX", date(2026, 10, 2))

    assert uri == f"s3://{BUCKET}/{key}"
    assert fake_s3[key] == {"jobs": ["original"]}


@responses.activate
def test_main_skips_landed_pairs_and_stops_on_access_error(
    jsearch_env: None, fake_s3: dict[str, dict]
) -> None:
    for role in fetch_jobs.SAMPLE_ROLES:
        for location in fetch_jobs.SAMPLE_LOCATIONS:
            fake_s3[fetch_jobs.raw_key(role, location)] = {}
    for role in fetch_jobs.SAMPLE_ROLES[:2]:
        del fake_s3[fetch_jobs.raw_key(role, fetch_jobs.SAMPLE_LOCATIONS[0])]
    responses.get(fetch_jobs.JSEARCH_URL, status=403, json={"message": "Invalid API key."})

    assert fetch_jobs.main() == 1
    assert len(responses.calls) == 1  # landed pairs skipped; run stopped after the first 403


# --- fetch_bls ----------------------------------------------------------------

OEWS_HEADER = ("AREA", "OCC_CODE", "OCC_TITLE", "O_GROUP", "TOT_EMP", "A_MEDIAN")
# Rows copied from the May 2025 national release.
OEWS_ROWS = [
    ("99", "11-0000", "Management Occupations", "major", 11132700, 126520),
    ("99", "11-1011", "Chief Executives", "detailed", 204350, 213990),
    ("99", "27-2011", "Actors", "detailed", 55000, "*"),
]


@pytest.fixture
def bls_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLS_CONTACT_EMAIL", "dev@example.com")


def _oews_zip(header: tuple = OEWS_HEADER, rows: list[tuple] = OEWS_ROWS) -> bytes:
    """Build an in-memory zip shaped like oesm25nat.zip (one xlsx, data on the first sheet)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "national_M2025_dl"
    ws.append(header)
    for row in rows:
        ws.append(row)
    xlsx = io.BytesIO()
    wb.save(xlsx)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("oesm25nat/national_M2025_dl.xlsx", xlsx.getvalue())
    return archive.getvalue()


@responses.activate
def test_fetch_bls_outlook_parses_detailed_occupations(bls_env: None) -> None:
    responses.get(fetch_bls.OEWS_URL.format(yy=25), body=_oews_zip())

    records = fetch_bls.fetch_bls_outlook(reference_year=2025)

    assert records == [
        {
            "occupation_code": "11-1011",
            "title": "Chief Executives",
            "total_employment": 204350,
            "median_wage": 213990,
            "reference_year": 2025,
        },
        {
            "occupation_code": "27-2011",
            "title": "Actors",
            "total_employment": 55000,
            "median_wage": None,
            "reference_year": 2025,
        },
    ]
    assert "dev@example.com" in responses.calls[0].request.headers["User-Agent"]


@responses.activate
def test_fetch_bls_outlook_falls_back_when_latest_year_unpublished(bls_env: None) -> None:
    this_year = datetime.now(timezone.utc).year
    responses.get(
        fetch_bls.OEWS_URL.format(yy=(this_year - 1) % 100),
        status=301,
        headers={"Location": "https://www.bls.gov/oes/home.htm"},
    )
    responses.get(fetch_bls.OEWS_URL.format(yy=(this_year - 2) % 100), body=_oews_zip())

    records = fetch_bls.fetch_bls_outlook()

    assert {r["reference_year"] for r in records} == {this_year - 2}


@responses.activate
def test_fetch_bls_outlook_explains_403(bls_env: None) -> None:
    responses.get(fetch_bls.OEWS_URL.format(yy=25), status=403)
    with pytest.raises(fetch_bls.BLSError, match="BLS_CONTACT_EMAIL"):
        fetch_bls.fetch_bls_outlook(reference_year=2025)


@responses.activate
def test_fetch_bls_outlook_rejects_changed_schema(bls_env: None) -> None:
    header = ("AREA", "OCC_CODE", "OCC_TITLE", "O_GROUP", "TOT_EMP", "MEDIAN_WAGE")
    responses.get(fetch_bls.OEWS_URL.format(yy=25), body=_oews_zip(header=header))
    with pytest.raises(fetch_bls.BLSError, match="missing columns \\['A_MEDIAN'\\]"):
        fetch_bls.fetch_bls_outlook(reference_year=2025)


def test_save_bls_writes_dated_key(fake_s3: dict[str, dict]) -> None:
    uri = fetch_bls.save_to_s3([{"occupation_code": "11-1011"}], date(2026, 10, 2))

    assert uri == f"s3://{BUCKET}/bls/raw/2026-10-02.json"
    assert fake_s3["bls/raw/2026-10-02.json"]["record_count"] == 1


def test_save_bls_rejects_empty_dataset(fake_s3: dict[str, dict]) -> None:
    with pytest.raises(ValueError, match="empty BLS dataset"):
        fetch_bls.save_to_s3([])
    assert fake_s3 == {}
