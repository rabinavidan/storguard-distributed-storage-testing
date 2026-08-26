"""Security tests — auth enforcement, namespace isolation, boundary inputs, error safety.

Every test runs against the live cluster. No mocks — we prove the actual S3 service
rejects bad inputs cleanly rather than crashing, leaking data, or returning 500s.
"""

from __future__ import annotations

import uuid
from typing import List

import allure
import pytest

from storguard.clients.s3_client import S3Client, S3Config
from storguard.integrity.validator import generate_test_data
from storguard.models import OperationStatus


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _bad_client(base_config: S3Config, access_key: str, secret_key: str) -> S3Client:
    return S3Client(S3Config(
        endpoint=base_config.endpoint,
        access_key=access_key,
        secret_key=secret_key,
        region=base_config.region,
    ))


# ─── Authentication enforcement ───────────────────────────────────────────────

@allure.epic("Security")
@allure.feature("Authentication")
@pytest.mark.security
class TestAuthEnforcement:

    @allure.story("Wrong credentials are rejected on upload")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_wrong_credentials_rejected_on_upload(self, s3_config: S3Config, test_bucket: str):
        with allure.step("Create client with wrong secret key"):
            bad = _bad_client(s3_config, "storguard", "totally_wrong_secret")

        with allure.step("Attempt upload with bad credentials"):
            result = bad.upload_object(test_bucket, "sec/probe", b"should not land")

        with allure.step("Assert request was rejected"):
            assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED), (
                f"Expected auth failure, got {result.status}: {result.error}"
            )
            allure.attach(
                f"status={result.status}\nerror_code={result.error_code}\nerror={result.error}",
                name="rejection-detail",
                attachment_type=allure.attachment_type.TEXT,
            )

    @allure.story("Wrong credentials are rejected on download")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_wrong_credentials_rejected_on_download(
        self, s3: S3Client, s3_config: S3Config, test_bucket: str
    ):
        key = f"sec/{uuid.uuid4().hex}"
        s3.upload_object(test_bucket, key, b"real content")

        bad = _bad_client(s3_config, "storguard", "wrong_secret")
        result = bad.download_object(test_bucket, key)

        assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED)

    @allure.story("Wrong credentials are rejected on delete")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_wrong_credentials_rejected_on_delete(
        self, s3: S3Client, s3_config: S3Config, test_bucket: str
    ):
        key = f"sec/{uuid.uuid4().hex}"
        s3.upload_object(test_bucket, key, b"protected")

        bad = _bad_client(s3_config, "storguard", "wrong_secret")
        result = bad.delete_object(test_bucket, key)

        assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED)

        # Verify the object was NOT deleted — bad client must not have affected data
        verify = s3.download_object(test_bucket, key)
        assert verify.succeeded, "Object was deleted by an unauthorised client — data integrity failure"

    @allure.story("Wrong access key is rejected")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_wrong_access_key_rejected(self, s3_config: S3Config, test_bucket: str):
        bad = _bad_client(s3_config, "nonexistent_user", "storguard_secret_123")
        result = bad.upload_object(test_bucket, "sec/probe", b"data")
        assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED)

    @allure.story("Empty credentials are rejected")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_empty_credentials_rejected(self, s3_config: S3Config, test_bucket: str):
        bad = _bad_client(s3_config, "", "")
        result = bad.upload_object(test_bucket, "sec/empty-cred", b"data")
        assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED)

    @allure.story("Health check does not expose credentials")
    @allure.severity(allure.severity_level.NORMAL)
    def test_health_endpoint_requires_no_creds_but_exposes_nothing_sensitive(
        self, s3: S3Client
    ):
        """The health endpoint must be reachable but must not leak bucket names,
        credentials, or internal server details in its response."""
        import httpx
        with allure.step("Call MinIO health endpoint unauthenticated"):
            resp = httpx.get("http://localhost:9000/minio/health/live", timeout=5)

        with allure.step("Assert 200 with no sensitive body content"):
            assert resp.status_code == 200
            body = resp.text
            assert "storguard" not in body.lower(), "Credentials leaked in health response"
            assert "secret" not in body.lower(), "Secret visible in health response"
            allure.attach(
                f"status={resp.status_code}\nbody={body!r}",
                name="health-response",
                attachment_type=allure.attachment_type.TEXT,
            )


# ─── Namespace isolation ──────────────────────────────────────────────────────

@allure.epic("Security")
@allure.feature("Namespace Isolation")
@pytest.mark.security
class TestNamespaceIsolation:

    @allure.story("Objects in one bucket are not listed from another")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_objects_not_visible_across_buckets(self, s3: S3Client):
        bucket_a = f"ns-a-{uuid.uuid4().hex[:8]}"
        bucket_b = f"ns-b-{uuid.uuid4().hex[:8]}"
        s3.create_bucket(bucket_a)
        s3.create_bucket(bucket_b)
        try:
            key = f"secret-{uuid.uuid4().hex}"
            s3.upload_object(bucket_a, key, b"bucket A secret")

            with allure.step("List bucket B — must not see bucket A's objects"):
                listed = s3.list_objects(bucket_b)
            assert key not in listed, f"Object from bucket A leaked into bucket B: {key}"
        finally:
            for k in s3.list_objects(bucket_a):
                s3.delete_object(bucket_a, k)
            s3.delete_bucket(bucket_a)
            s3.delete_bucket(bucket_b)

    @allure.story("Direct download across buckets returns NOT_FOUND")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_cross_bucket_download_returns_not_found(self, s3: S3Client):
        bucket_a = f"ns-a-{uuid.uuid4().hex[:8]}"
        bucket_b = f"ns-b-{uuid.uuid4().hex[:8]}"
        s3.create_bucket(bucket_a)
        s3.create_bucket(bucket_b)
        try:
            key = f"private/{uuid.uuid4().hex}"
            s3.upload_object(bucket_a, key, b"private data")

            with allure.step("Download key from bucket B — must not see bucket A's object"):
                result = s3.download_object(bucket_b, key)

            assert result.status == OperationStatus.NOT_FOUND, (
                f"Cross-bucket read returned {result.status} — possible data leak"
            )
        finally:
            for k in s3.list_objects(bucket_a):
                s3.delete_object(bucket_a, k)
            s3.delete_bucket(bucket_a)
            s3.delete_bucket(bucket_b)


# ─── Boundary and injection inputs ───────────────────────────────────────────

@allure.epic("Security")
@allure.feature("Input Boundary Safety")
@pytest.mark.security
@pytest.mark.negative
class TestBoundaryInputs:

    @allure.story("Path traversal key is rejected or contained")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_path_traversal_key_safe(self, s3: S3Client, test_bucket: str):
        """S3 must not allow `../` sequences to escape the bucket namespace."""
        traversal_keys = [
            "../etc/passwd",
            "../../secret",
            "valid/../../../escape",
            "%2e%2e%2fetc%2fpasswd",
        ]
        for key in traversal_keys:
            with allure.step(f"Attempt upload with traversal key: {key!r}"):
                result = s3.upload_object(test_bucket, key, b"traversal probe")
                # Accept: either rejected outright OR stored as a literal key (contained)
                # Fail only if it causes a server error (500) or exposes internal paths
                assert result.error_code != "InternalError", (
                    f"Path traversal key caused InternalError: {key!r}"
                )
                allure.attach(
                    f"key={key!r}\nstatus={result.status}\nerror_code={result.error_code}",
                    name=f"traversal-result-{traversal_keys.index(key)}",
                    attachment_type=allure.attachment_type.TEXT,
                )

    @allure.story("Maximum length key (1024 bytes) is handled cleanly")
    @allure.severity(allure.severity_level.NORMAL)
    def test_max_length_key(self, s3: S3Client, test_bucket: str):
        max_key = "a" * 1024
        result = s3.upload_object(test_bucket, max_key, b"max key test")
        # Must not crash with InternalError — either succeed or return a clean error
        assert result.status != OperationStatus.FAILED or result.error_code is not None, (
            "Max-length key caused unclassified failure"
        )
        allure.attach(
            f"key_len={len(max_key)}\nstatus={result.status}\nerror_code={result.error_code}",
            name="max-key-result",
            attachment_type=allure.attachment_type.TEXT,
        )

    @allure.story("Oversized key (>1024 bytes) is rejected cleanly")
    @allure.severity(allure.severity_level.NORMAL)
    def test_oversized_key_rejected_cleanly(self, s3: S3Client, test_bucket: str):
        oversized_key = "b" * 1025
        result = s3.upload_object(test_bucket, oversized_key, b"oversized key probe")
        # Must fail cleanly — not a 500, not a Python exception propagating up
        assert result.status in (OperationStatus.FAILED, OperationStatus.NOT_FOUND), (
            f"Oversized key unexpectedly succeeded or caused crash: {result.status}"
        )

    @allure.story("SQL injection in key name is stored literally or rejected")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_sql_injection_in_key_contained(self, s3: S3Client, test_bucket: str):
        """S3 object keys are not executed — they are opaque byte strings.
        This test confirms no InternalError (500) is returned."""
        injection_key = "'; DROP TABLE objects; --"
        result = s3.upload_object(test_bucket, injection_key, b"sql injection probe")
        assert result.error_code != "InternalError", (
            "SQL injection in key triggered InternalError — possible unsafe handling"
        )

    @allure.story("Null bytes in key are rejected or contained")
    @allure.severity(allure.severity_level.NORMAL)
    def test_null_byte_in_key(self, s3: S3Client, test_bucket: str):
        null_key = "valid\x00hidden"
        result = s3.upload_object(test_bucket, null_key, b"null byte probe")
        assert result.error_code != "InternalError"

    @allure.story("Very large object upload completes or fails cleanly")
    @allure.severity(allure.severity_level.NORMAL)
    def test_large_object_no_crash(self, s3: S3Client, test_bucket: str):
        """100 MB upload must complete or return a clean error — no timeout propagation crash."""
        data = generate_test_data(100 * 1024 * 1024)
        key = f"sec/large-{uuid.uuid4().hex}"
        result = s3.upload_object(test_bucket, key, data)
        assert result.status in (OperationStatus.SUCCESS, OperationStatus.FAILED), (
            f"Large upload caused unexpected status: {result.status}"
        )
        allure.attach(
            f"size={len(data):,} bytes\nstatus={result.status}\n"
            f"duration={result.duration_ms:.0f}ms\nerror={result.error}",
            name="large-upload-result",
            attachment_type=allure.attachment_type.TEXT,
        )


# ─── Error safety ─────────────────────────────────────────────────────────────

@allure.epic("Security")
@allure.feature("Error Safety")
@pytest.mark.security
@pytest.mark.negative
class TestErrorSafety:

    @allure.story("Download from nonexistent bucket returns clean error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_nonexistent_bucket_clean_error(self, s3: S3Client):
        result = s3.download_object("bucket-that-does-not-exist-xyz123", "any/key")
        assert result.status in (OperationStatus.NOT_FOUND, OperationStatus.FAILED)
        assert result.error_code is not None, "Missing error code on nonexistent bucket"

    @allure.story("Delete from nonexistent bucket returns clean error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_delete_nonexistent_bucket_clean_error(self, s3: S3Client):
        result = s3.delete_object("bucket-xyz-does-not-exist", "any/key")
        assert result.status in (OperationStatus.NOT_FOUND, OperationStatus.FAILED)

    @allure.story("Listing a nonexistent bucket returns clean error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_list_nonexistent_bucket_clean_error(self, s3: S3Client):
        try:
            keys = s3.list_objects("bucket-xyz-does-not-exist")
            # Some S3 impls return empty list, others raise — both are acceptable
            assert isinstance(keys, list)
        except Exception as exc:
            # Must be a recognised S3 error, not an unhandled Python exception
            assert "NoSuchBucket" in str(exc) or "404" in str(exc), (
                f"Unexpected raw exception on nonexistent bucket: {exc}"
            )

    @allure.story("Upload to nonexistent bucket returns clean error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_upload_nonexistent_bucket_clean_error(self, s3: S3Client):
        result = s3.upload_object("bucket-xyz-does-not-exist", "key", b"data")
        assert result.status in (OperationStatus.NOT_FOUND, OperationStatus.FAILED)
        assert result.error_code is not None

    @allure.story("Metadata on nonexistent object returns clean error")
    @allure.severity(allure.severity_level.NORMAL)
    def test_metadata_nonexistent_object_clean_error(self, s3: S3Client, test_bucket: str):
        try:
            meta = s3.get_object_metadata(test_bucket, "does/not/exist")
            pytest.fail(f"Expected exception, got metadata: {meta}")
        except Exception as exc:
            assert "404" in str(exc) or "NoSuchKey" in str(exc) or "Not Found" in str(exc), (
                f"Unexpected exception type: {exc}"
            )
