"""boto3 helpers for writing, checking, and listing objects in S3."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class S3OperationError(RuntimeError):
    """Raised when an S3 call fails for any reason other than a missing key."""


def require_env(name: str) -> str:
    """Return an environment variable's value, failing loudly if it is unset.

    Args:
        name: Environment variable name.

    Returns:
        The variable's non-empty value.

    Raises:
        ValueError: If the variable is unset or empty.
    """
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"Environment variable {name} is not set. Add it to .env (see 'Secrets needed' in CLAUDE.md)."
        )
    return value


@lru_cache(maxsize=1)
def _client() -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id=require_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=require_env("AWS_SECRET_ACCESS_KEY"),
        region_name=require_env("AWS_REGION"),
    )


def upload_json(bucket: str, key: str, data: dict) -> None:
    """Serialize a dict as UTF-8 JSON and write it to s3://bucket/key.

    Args:
        bucket: Target S3 bucket name.
        key: Object key to write.
        data: JSON-serializable dict to store.

    Returns:
        None.

    Raises:
        ValueError: If data is not JSON-serializable or an AWS env var is missing.
        S3OperationError: If the PutObject call fails.
    """
    try:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Data for s3://{bucket}/{key} is not JSON-serializable: {exc}") from exc
    upload_bytes(bucket, key, body, "application/json")


def upload_bytes(bucket: str, key: str, body: bytes, content_type: str) -> None:
    """Write raw bytes (e.g. a Parquet file) to s3://bucket/key, replacing any object there.

    Args:
        bucket: Target S3 bucket name.
        key: Object key to write.
        body: The file's bytes.
        content_type: MIME type stored with the object.

    Returns:
        None.

    Raises:
        ValueError: If an AWS env var is missing.
        S3OperationError: If the PutObject call fails.
    """
    try:
        _client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    except (ClientError, BotoCoreError) as exc:
        raise S3OperationError(f"Failed to upload s3://{bucket}/{key}: {exc}") from exc

    logger.info("Uploaded %d bytes to s3://%s/%s", len(body), bucket, key)


def key_exists(bucket: str, key: str) -> bool:
    """Check whether an object exists at s3://bucket/key.

    Args:
        bucket: S3 bucket name.
        key: Object key to check.

    Returns:
        True if the object exists, False if S3 reports it missing.

    Raises:
        ValueError: If an AWS env var is missing.
        S3OperationError: On any other S3 error (e.g. 403, which S3 returns for
            missing keys when the caller lacks s3:ListBucket).
    """
    try:
        _client().head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in _NOT_FOUND_CODES:
            return False
        hint = " (403 can mean the key is missing and s3:ListBucket is not granted)" if code == "403" else ""
        raise S3OperationError(f"Could not check s3://{bucket}/{key}: {exc}{hint}") from exc
    except BotoCoreError as exc:
        raise S3OperationError(f"Could not check s3://{bucket}/{key}: {exc}") from exc
    return True


def list_keys(bucket: str, prefix: str) -> list[str]:
    """List every object key under a prefix, following pagination.

    Args:
        bucket: S3 bucket name.
        prefix: Key prefix to list (use "" for the whole bucket).

    Returns:
        All matching keys, in the order S3 returns them.

    Raises:
        ValueError: If an AWS env var is missing.
        S3OperationError: If any ListObjectsV2 page fails.
    """
    keys: list[str] = []
    paginator = _client().get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
    except (ClientError, BotoCoreError) as exc:
        raise S3OperationError(f"Failed to list s3://{bucket}/{prefix}: {exc}") from exc
    return keys
