"""Smoke tests — fast cluster health checks that block the pipeline early."""

from __future__ import annotations

import uuid

import allure
import pytest

from storguard.clients.s3_client import S3Client


@allure.epic("Smoke")
@allure.feature("Cluster Health")
@pytest.mark.smoke
class TestClusterSmoke:

    @allure.story("S3 API reachability")
    @allure.title("S3 endpoint responds to health probe before any test runs")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_s3_api_reachable(self, s3: S3Client):
        with allure.step("Call s3.health_check()"):
            result = s3.health_check()

        with allure.step("Assert health_check returns True"):
            assert result, "S3 endpoint not responding"

    @allure.story("Bucket lifecycle")
    @allure.title("Bucket can be created and deleted within a single test")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_bucket_lifecycle(self, s3: S3Client):
        with allure.step("Generate unique bucket name"):
            bucket = f"smoke-{uuid.uuid4().hex[:8]}"

        with allure.step(f"Create bucket '{bucket}'"):
            try:
                create = s3.create_bucket(bucket)
                assert create.succeeded, create.error
            finally:
                with allure.step(f"Delete bucket '{bucket}' (cleanup)"):
                    s3.delete_bucket(bucket)

    @allure.story("Object roundtrip")
    @allure.title("Upload followed by download returns identical SHA-256 checksum")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_small_object_roundtrip(self, s3: S3Client, test_bucket: str):
        with allure.step("Prepare 20-byte payload and unique key"):
            key = f"smoke/{uuid.uuid4().hex}"
            data = b"storguard smoke test"

        with allure.step(f"Upload object '{key}'"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, upload.error

        with allure.step(f"Download object '{key}'"):
            download = s3.download_object(test_bucket, key)
            assert download.succeeded, download.error

        with allure.step("Assert SHA-256 checksums match"):
            assert download.checksum_sha256 == upload.checksum_sha256
