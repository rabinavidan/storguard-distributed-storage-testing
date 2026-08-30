"""Low-level S3 client — thin boto3 wrapper that returns typed OperationResult objects."""

import hashlib
import io
import time
from dataclasses import dataclass
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointResolutionError

from storguard.models import OperationResult, OperationStatus


@dataclass
class S3Config:
    endpoint: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"
    connect_timeout: int = 10
    read_timeout: int = 30
    max_retries: int = 3


class S3Client:
    def __init__(self, config: S3Config) -> None:
        self._cfg = config
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            config=Config(
                connect_timeout=config.connect_timeout,
                read_timeout=config.read_timeout,
                retries={"max_attempts": config.max_retries, "mode": "standard"},
            ),
        )

    # ─── Bucket operations ────────────────────────────────────────────────────

    def create_bucket(self, bucket: str) -> OperationResult:
        start = time.monotonic()
        try:
            self._client.create_bucket(Bucket=bucket)
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=bucket,
                key="",
            )
        except ClientError as exc:
            return _s3_error(exc, start, bucket, "")

    def delete_bucket(self, bucket: str) -> OperationResult:
        start = time.monotonic()
        try:
            self._client.delete_bucket(Bucket=bucket)
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=bucket,
                key="",
            )
        except ClientError as exc:
            return _s3_error(exc, start, bucket, "")

    # ─── Object operations ────────────────────────────────────────────────────

    def upload_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> OperationResult:
        start = time.monotonic()
        checksum = hashlib.sha256(data).hexdigest()
        try:
            self._client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": checksum},
            )
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=bucket,
                key=key,
                size_bytes=len(data),
                checksum_sha256=checksum,
            )
        except ClientError as exc:
            return _s3_error(exc, start, bucket, key)

    def download_object(self, bucket: str, key: str) -> OperationResult:
        start = time.monotonic()
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            data = response["Body"].read()
            checksum = hashlib.sha256(data).hexdigest()
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=bucket,
                key=key,
                size_bytes=len(data),
                checksum_sha256=checksum,
            )
        except ClientError as exc:
            return _s3_error(exc, start, bucket, key)

    def download_bytes(self, bucket: str, key: str) -> Optional[bytes]:
        """Return the raw object body, or None if it can't be read.

        download_object() is used for integrity/metrics tracking and discards the
        body after checksumming; this is for callers that need the actual content
        back (e.g. reading a snapshot manifest).
        """
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except ClientError:
            return None

    def copy_object(
        self, source_bucket: str, source_key: str, dest_bucket: str, dest_key: str
    ) -> OperationResult:
        """Server-side copy — the SHA-256 stored in the source's metadata travels
        with the copy (MetadataDirective defaults to COPY), so integrity can be
        re-verified on the destination without re-uploading any bytes."""
        start = time.monotonic()
        try:
            self._client.copy_object(
                Bucket=dest_bucket,
                Key=dest_key,
                CopySource={"Bucket": source_bucket, "Key": source_key},
            )
            meta = self.get_object_metadata(dest_bucket, dest_key)
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=dest_bucket,
                key=dest_key,
                size_bytes=meta["size"],
                checksum_sha256=meta["metadata"].get("sha256"),
            )
        except ClientError as exc:
            return _s3_error(exc, start, dest_bucket, dest_key)

    def delete_object(self, bucket: str, key: str) -> OperationResult:
        start = time.monotonic()
        try:
            self._client.delete_object(Bucket=bucket, Key=key)
            return OperationResult(
                status=OperationStatus.SUCCESS,
                duration_ms=_elapsed_ms(start),
                bucket=bucket,
                key=key,
            )
        except ClientError as exc:
            return _s3_error(exc, start, bucket, key)

    def list_objects(self, bucket: str, prefix: str = "") -> List[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        response = self._client.head_object(Bucket=bucket, Key=key)
        return {
            "size": response["ContentLength"],
            "content_type": response.get("ContentType", ""),
            "etag": response.get("ETag", ""),
            "metadata": response.get("Metadata", {}),
        }

    def health_check(self) -> bool:
        try:
            self._client.list_buckets()
            return True
        except Exception:
            return False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _s3_error(exc: ClientError, start: float, bucket: str, key: str) -> OperationResult:
    code = exc.response["Error"]["Code"]
    status_map = {
        "NoSuchKey": OperationStatus.NOT_FOUND,
        "NoSuchBucket": OperationStatus.NOT_FOUND,
        "AccessDenied": OperationStatus.UNAUTHORIZED,
        "InvalidAccessKeyId": OperationStatus.UNAUTHORIZED,
        "RequestTimeout": OperationStatus.TIMEOUT,
        "ServiceUnavailable": OperationStatus.FAILED,
    }
    return OperationResult(
        status=status_map.get(code, OperationStatus.FAILED),
        duration_ms=_elapsed_ms(start),
        bucket=bucket,
        key=key,
        error=str(exc),
        error_code=code,
    )
