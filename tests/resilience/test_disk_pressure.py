"""Disk pressure resilience tests — fill disk on a node, verify clean errors, verify recovery.

Uses fallocate inside the minio1 container to consume available disk space,
then verifies the cluster handles ENOSPC conditions without data corruption on
remaining healthy nodes.
"""

from __future__ import annotations

import uuid

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import IntegrityValidator, generate_test_data
from storguard.models import OperationStatus

TARGET_CONTAINER = "storguard-minio1"
DATA_PATH = "/data"
FILL_MB = 4096  # 4 GB — enough to trigger disk pressure in a local Docker volume


@allure.epic("Resilience")
@allure.feature("Disk Pressure")
@pytest.mark.resilience
class TestDiskPressure:

    @allure.story("Cluster handles disk pressure on one node without data corruption")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_data_integrity_preserved_under_disk_pressure(
        self,
        s3: S3Client,
        chaos: ChaosController,
        test_bucket: str,
        integrity: IntegrityValidator,
    ):
        data = generate_test_data(256 * 1024, seed=7)  # 256 KB
        key = f"disk-pressure-probe/{uuid.uuid4().hex}"

        with allure.step("Upload reference object before disk pressure"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, f"Pre-fault upload failed: {upload.error}"

        with allure.step(f"Fill disk on {TARGET_CONTAINER} with {FILL_MB} MB"):
            fill_timeline = chaos.apply_disk_pressure(TARGET_CONTAINER, fill_mb=FILL_MB, path=DATA_PATH)
            allure.attach(
                f"fault={fill_timeline.fault_type}\ninjected_at={fill_timeline.fault_injected_at:.3f}\n"
                f"target={TARGET_CONTAINER}\nfill_mb={FILL_MB}\npath={DATA_PATH}",
                name="disk-fill-result",
                attachment_type=allure.attachment_type.TEXT,
            )

        try:
            with allure.step("Verify reference object still readable under disk pressure"):
                report = integrity.verify(test_bucket, key, data)
                allure.attach(
                    f"checksum_match={report.checksum_match}\n"
                    f"size_match={report.size_match}\n"
                    f"passed={report.passed}",
                    name="integrity-under-disk-pressure",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert report.passed, (
                    f"Data corrupted under disk pressure on {TARGET_CONTAINER}: {report.summary()}"
                )

        finally:
            with allure.step("Release disk pressure"):
                release = chaos._docker.release_disk(TARGET_CONTAINER, DATA_PATH)
                allure.attach(
                    f"exit_code={release.exit_code}\n{release.stdout}",
                    name="disk-release-result",
                    attachment_type=allure.attachment_type.TEXT,
                )

    @allure.story("Write operations return clean error under disk full condition")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_write_fails_cleanly_when_disk_full(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str
    ):
        with allure.step(f"Fill disk on {TARGET_CONTAINER}"):
            chaos.apply_disk_pressure(TARGET_CONTAINER, fill_mb=FILL_MB, path=DATA_PATH)

        try:
            with allure.step("Attempt write — must return clean error, not Python exception"):
                data = generate_test_data(10 * 1024 * 1024)  # 10 MB
                result = s3.upload_object(test_bucket, f"disk-full/{uuid.uuid4().hex}", data)
                allure.attach(
                    f"status={result.status}\nerror_code={result.error_code}\nerror={result.error}",
                    name="disk-full-upload-result",
                    attachment_type=allure.attachment_type.TEXT,
                )
                # Either succeeds (other nodes have space) or fails with a known S3 error — never crashes
                assert result.status in (
                    OperationStatus.SUCCESS,
                    OperationStatus.FAILED,
                    OperationStatus.TIMEOUT,
                ), f"Unexpected status under disk pressure: {result.status}"

                if result.status == OperationStatus.FAILED:
                    assert result.error_code is not None, (
                        "Write failure under disk pressure must include an error code"
                    )

        finally:
            with allure.step("Release disk pressure"):
                chaos._docker.release_disk(TARGET_CONTAINER, DATA_PATH)

    @allure.story("Cluster recovers writes after disk pressure is released")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_cluster_recovers_after_disk_pressure(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str, integrity: IntegrityValidator
    ):
        data = generate_test_data(64 * 1024, seed=13)
        key = f"recovery-probe/{uuid.uuid4().hex}"

        with allure.step("Apply disk pressure"):
            chaos.apply_disk_pressure(TARGET_CONTAINER, fill_mb=FILL_MB, path=DATA_PATH)

        with allure.step("Release disk pressure"):
            chaos._docker.release_disk(TARGET_CONTAINER, DATA_PATH)

        with allure.step("Upload after pressure released — must succeed"):
            result = s3.upload_object(test_bucket, key, data)
            allure.attach(
                f"status={result.status}\nerror={result.error}",
                name="post-recovery-upload",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert result.succeeded, (
                f"Upload failed after disk pressure was released: {result.error}"
            )

        with allure.step("Verify post-recovery data integrity"):
            report = integrity.verify(test_bucket, key, data)
            assert report.passed, f"Data corrupted after disk recovery: {report.summary()}"
            allure.attach(
                f"checksum_match={report.checksum_match}\npassed={report.passed}",
                name="post-recovery-integrity",
                attachment_type=allure.attachment_type.TEXT,
            )
