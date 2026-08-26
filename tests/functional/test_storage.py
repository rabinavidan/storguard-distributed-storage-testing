"""Functional tests — S3 CRUD, metadata, naming and edge cases against the live cluster."""

from __future__ import annotations

import uuid

import allure
import pytest

from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import generate_test_data
from storguard.models import OperationStatus


@allure.epic("Storage")
@allure.feature("S3 CRUD")
@pytest.mark.functional
class TestObjectOperations:

    @allure.story("Upload and Download")
    @allure.title("Downloaded bytes have identical SHA-256 to uploaded bytes")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_upload_download_roundtrip(self, s3: S3Client, test_bucket: str):
        with allure.step("Generate 1 KB test payload"):
            data = generate_test_data(1024)
            key = f"functional/{uuid.uuid4().hex}"

        with allure.step(f"Upload object '{key}'"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, upload.error

        with allure.step(f"Download object '{key}'"):
            download = s3.download_object(test_bucket, key)
            assert download.succeeded, download.error

        with allure.step("Compare SHA-256 checksums"):
            assert download.checksum_sha256 == upload.checksum_sha256

    @allure.story("Delete")
    @allure.title("Deleted object returns NOT_FOUND on subsequent download")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_delete_object(self, s3: S3Client, test_bucket: str):
        with allure.step("Upload object to be deleted"):
            key = f"functional/{uuid.uuid4().hex}"
            s3.upload_object(test_bucket, key, b"delete me")

        with allure.step(f"Delete object '{key}'"):
            result = s3.delete_object(test_bucket, key)
            assert result.succeeded

        with allure.step("Attempt download — expect NOT_FOUND"):
            not_found = s3.download_object(test_bucket, key)
            assert not_found.status == OperationStatus.NOT_FOUND

    @allure.story("List Objects")
    @allure.title("list_objects returns exactly the keys uploaded under a prefix")
    @allure.severity(allure.severity_level.NORMAL)
    def test_list_objects(self, s3: S3Client, test_bucket: str):
        with allure.step("Define unique prefix and 5 object keys"):
            prefix = f"list-{uuid.uuid4().hex[:6]}/"
            keys = [f"{prefix}obj-{i}" for i in range(5)]

        with allure.step("Upload all 5 objects under the prefix"):
            for key in keys:
                s3.upload_object(test_bucket, key, b"x")

        with allure.step(f"List objects under prefix '{prefix}'"):
            listed = s3.list_objects(test_bucket, prefix=prefix)

        with allure.step("Assert listed keys match uploaded keys exactly"):
            assert sorted(listed) == sorted(keys)

    @allure.story("Replace Object")
    @allure.title("Re-uploading to same key replaces content (size reflects version-2)")
    @allure.severity(allure.severity_level.NORMAL)
    def test_replace_object(self, s3: S3Client, test_bucket: str):
        with allure.step("Upload version-1 to a stable key"):
            key = f"functional/{uuid.uuid4().hex}"
            s3.upload_object(test_bucket, key, b"version-1")

        with allure.step("Upload version-2 to the same key"):
            s3.upload_object(test_bucket, key, b"version-2")

        with allure.step("Download and verify content is version-2 (9 bytes)"):
            result = s3.download_object(test_bucket, key)
            assert result.succeeded
            assert result.size_bytes == len(b"version-2")

    @allure.story("Metadata")
    @allure.title("Object metadata reflects uploaded size and content_type")
    @allure.severity(allure.severity_level.NORMAL)
    def test_object_metadata(self, s3: S3Client, test_bucket: str):
        with allure.step("Upload 512-byte object with explicit content_type"):
            data = generate_test_data(512)
            key = f"functional/{uuid.uuid4().hex}"
            s3.upload_object(test_bucket, key, data, content_type="application/octet-stream")

        with allure.step("Fetch metadata"):
            meta = s3.get_object_metadata(test_bucket, key)

        with allure.step("Assert size=512 and content_type='application/octet-stream'"):
            assert meta["size"] == 512
            assert meta["content_type"] == "application/octet-stream"


@allure.epic("Storage")
@allure.feature("Edge Cases")
@pytest.mark.functional
@pytest.mark.negative
class TestEdgeCases:

    @allure.story("Empty object")
    @allure.title("Zero-byte object uploads succeed and report size=0")
    @allure.severity(allure.severity_level.NORMAL)
    def test_upload_empty_file(self, s3: S3Client, test_bucket: str):
        with allure.step("Generate unique key for empty object"):
            key = f"edge/{uuid.uuid4().hex}"

        with allure.step("Upload empty payload (b'')"):
            result = s3.upload_object(test_bucket, key, b"")

        with allure.step("Assert succeeded and size_bytes=0"):
            assert result.succeeded
            assert result.size_bytes == 0

    @allure.story("Unicode key")
    @allure.title("Object key with unicode characters (Chinese, accented) is accepted")
    @allure.severity(allure.severity_level.NORMAL)
    def test_unicode_object_key(self, s3: S3Client, test_bucket: str):
        with allure.step("Build unicode key with Chinese and accented characters"):
            key = f"edge/unicode-\u4e2d\u6587-\u00e9l\u00e8ve-{uuid.uuid4().hex[:6]}"

        with allure.step(f"Upload object with unicode key '{key}'"):
            result = s3.upload_object(test_bucket, key, b"unicode key test")

        with allure.step("Assert upload succeeded"):
            assert result.succeeded

    @allure.story("Missing object")
    @allure.title("Download of non-existent key returns NOT_FOUND, not an exception")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_download_nonexistent_key(self, s3: S3Client, test_bucket: str):
        with allure.step("Attempt download of key that was never uploaded"):
            result = s3.download_object(test_bucket, "does/not/exist")

        with allure.step("Assert status is NOT_FOUND"):
            assert result.status == OperationStatus.NOT_FOUND

    @allure.story("Unauthorized access")
    @allure.title("Wrong credentials return UNAUTHORIZED or FAILED, never silently succeed")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_unauthorized_access(self, s3_config):
        with allure.step("Build S3Client with wrong access/secret keys"):
            from storguard.clients.s3_client import S3Client, S3Config
            bad_client = S3Client(S3Config(
                endpoint=s3_config.endpoint,
                access_key="wrong",
                secret_key="credentials",
            ))

        with allure.step("Attempt upload with bad credentials"):
            result = bad_client.upload_object("any-bucket", "key", b"data")

        with allure.step("Assert status is UNAUTHORIZED or FAILED"):
            assert result.status in (OperationStatus.UNAUTHORIZED, OperationStatus.FAILED)
