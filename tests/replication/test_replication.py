"""Replication and failover tests — primary -> secondary async replication.

Two independent MinIO sites (the 4-node erasure-coded primary behind the
gateway, and a standalone single-node secondary) with a small Python
ReplicationWorker copying between them. This proves out the distributed-systems
story a real replication engine would need to handle: replication lag is
observable rather than hidden behind a sleep, a failover read against the
secondary must return correct data, and a write that hasn't replicated yet
defines an explicit, expected data-loss window (RPO) rather than an undefined one.
"""

from __future__ import annotations

import uuid

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import generate_test_data
from storguard.models import OperationStatus
from storguard.replication.worker import ReplicationWorker

GATEWAY_CONTAINER = "storguard-gateway"


@allure.epic("Resilience")
@allure.feature("Replication & Failover")
@pytest.mark.replication
class TestReplication:

    @allure.story("A write on primary appears on secondary after sync")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_write_replicates_to_secondary(
        self, s3: S3Client, secondary_s3: S3Client, replication_bucket: str
    ):
        key = f"repl/{uuid.uuid4().hex}"
        data = generate_test_data(32 * 1024, seed=1)

        with allure.step("Write to primary"):
            upload = s3.upload_object(replication_bucket, key, data)
            assert upload.succeeded

        with allure.step("Secondary does not have it yet (replication hasn't run)"):
            before = secondary_s3.download_object(replication_bucket, key)
            assert before.status == OperationStatus.NOT_FOUND

        with allure.step("Run one replication cycle"):
            worker = ReplicationWorker(s3, secondary_s3, replication_bucket)
            status = worker.sync_once()
            allure.attach(
                f"replicated={status.replicated_keys}\nfailed={status.failed_keys}\n"
                f"lag_seconds={status.lag_seconds:.3f}",
                name="sync-status",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert key in status.replicated_keys
            assert not status.failed_keys

        with allure.step("Secondary now holds a byte-identical copy"):
            after = secondary_s3.download_object(replication_bucket, key)
            assert after.succeeded
            assert after.checksum_sha256 == upload.checksum_sha256

    @allure.story("Replication lag is observable and re-sync is idempotent")
    @allure.severity(allure.severity_level.NORMAL)
    def test_replication_lag_is_observable(
        self, s3: S3Client, secondary_s3: S3Client, replication_bucket: str
    ):
        worker = ReplicationWorker(s3, secondary_s3, replication_bucket)

        with allure.step("Write 10 objects to primary"):
            for i in range(10):
                s3.upload_object(
                    replication_bucket, f"repl-batch/{i:03d}", generate_test_data(1024, seed=i)
                )

        with allure.step("First sync — replicates all 10, lag is measurable"):
            status = worker.sync_once()
            allure.attach(
                f"replicated={len(status.replicated_keys)} lag_seconds={status.lag_seconds:.3f}",
                name="first-sync",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert len(status.replicated_keys) == 10
            assert status.lag_seconds >= 0

        with allure.step("Second sync with no new writes — nothing left to replicate"):
            status2 = worker.sync_once()
            assert status2.replicated_keys == []
            assert status2.failed_keys == []

    @allure.story("Reads failover to the secondary when the primary gateway is down")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_failover_read_after_primary_down(
        self,
        s3: S3Client,
        secondary_s3: S3Client,
        chaos: ChaosController,
        replication_bucket: str,
    ):
        key = f"repl-failover/{uuid.uuid4().hex}"
        data = generate_test_data(16 * 1024, seed=42)

        with allure.step("Write to primary and replicate to secondary"):
            upload = s3.upload_object(replication_bucket, key, data)
            assert upload.succeeded
            worker = ReplicationWorker(s3, secondary_s3, replication_bucket)
            worker.sync_once()

        with allure.step("Stop the primary gateway — primary site unreachable"):
            with chaos.node_stopped(GATEWAY_CONTAINER):

                with allure.step("Failover read from secondary succeeds with correct checksum"):
                    failover_read = secondary_s3.download_object(replication_bucket, key)
                    assert failover_read.succeeded, "Failover read from secondary failed"
                    assert failover_read.checksum_sha256 == upload.checksum_sha256

        with allure.step("Primary gateway restarts and serves the same data again"):
            recovered = s3.download_object(replication_bucket, key)
            assert recovered.succeeded
            assert recovered.checksum_sha256 == upload.checksum_sha256

    @allure.story("An unreplicated write defines an explicit recovery-point window")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_unsynced_write_is_the_documented_data_loss_window(
        self, s3: S3Client, secondary_s3: S3Client, replication_bucket: str
    ):
        """Async replication has an inherent RPO: anything written after the last
        sync and lost before the next one is gone from the secondary. That is
        the expected, documented behavior here — not a bug — and this test
        proves the window is exactly "since the last sync_once()", nothing more.
        """
        key = f"repl-rpo/{uuid.uuid4().hex}"
        data = generate_test_data(4096, seed=7)
        worker = ReplicationWorker(s3, secondary_s3, replication_bucket)

        with allure.step("Write to primary, do NOT sync yet"):
            upload = s3.upload_object(replication_bucket, key, data)
            assert upload.succeeded

        with allure.step("Secondary lacks the object — this is the expected RPO window"):
            gap_read = secondary_s3.download_object(replication_bucket, key)
            assert gap_read.status == OperationStatus.NOT_FOUND
            allure.attach(
                "Object written to primary but not yet replicated is absent from the "
                "secondary. This is the expected data-loss window for async "
                "replication, bounded by the sync interval — not an integrity bug.",
                name="documented-rpo-window",
                attachment_type=allure.attachment_type.TEXT,
            )

        with allure.step("Once sync runs, the object appears and the window closes"):
            status = worker.sync_once()
            assert key in status.replicated_keys
            closed = secondary_s3.download_object(replication_bucket, key)
            assert closed.succeeded
            assert closed.checksum_sha256 == upload.checksum_sha256
