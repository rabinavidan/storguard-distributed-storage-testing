"""Snapshot simulation tests — point-in-time create/list/restore/delete.

Models the classic snapshot story without proprietary storage hardware: write A,
snapshot, modify to B, restore, and prove byte-level integrity of the restored
data with SHA-256 — never trusting a copy just because the call reported success.
"""

from __future__ import annotations

import hashlib
import uuid

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import generate_test_data
from storguard.snapshot.service import SnapshotService


@allure.epic("Resilience")
@allure.feature("Snapshot Simulation")
@pytest.mark.snapshot
class TestSnapshotLifecycle:

    @allure.story("Restore reproduces the exact bytes captured at snapshot time")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_create_and_restore_roundtrip(
        self, s3: S3Client, snapshots: SnapshotService, test_bucket: str
    ):
        prefix = f"snap-roundtrip/{uuid.uuid4().hex}"
        key = f"{prefix}/data.bin"
        version_a = generate_test_data(64 * 1024, seed=1)
        version_b = generate_test_data(64 * 1024, seed=2)

        with allure.step("Write version A"):
            upload_a = s3.upload_object(test_bucket, key, version_a)
            assert upload_a.succeeded

        with allure.step("Create snapshot S1 of version A"):
            manifest = snapshots.create(test_bucket, source_prefix=prefix)
            allure.attach(
                f"snapshot_id={manifest.snapshot_id}\nobjects={manifest.object_count}",
                name="snapshot-created",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert manifest.object_count == 1

        with allure.step("Overwrite with version B"):
            upload_b = s3.upload_object(test_bucket, key, version_b)
            assert upload_b.succeeded
            current = s3.download_object(test_bucket, key)
            assert current.checksum_sha256 == upload_b.checksum_sha256

        with allure.step("Restore S1"):
            report = snapshots.restore(test_bucket, manifest.snapshot_id)
            allure.attach(
                f"restored={report.restored_keys}\nfailed={report.failed_keys}",
                name="restore-report",
                attachment_type=allure.attachment_type.TEXT,
            )
            assert report.passed, f"Restore reported failures: {report.failed_keys}"

        with allure.step("Verify restored data matches version A byte-for-byte"):
            restored = s3.download_object(test_bucket, key)
            assert restored.checksum_sha256 == upload_a.checksum_sha256, (
                "Restored object does not match the snapshotted version A"
            )

    @allure.story("Multiple snapshots of the same key coexist and restore independently")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_multiple_snapshots_coexist(
        self, s3: S3Client, snapshots: SnapshotService, test_bucket: str
    ):
        prefix = f"snap-multi/{uuid.uuid4().hex}"
        key = f"{prefix}/data.bin"

        with allure.step("Write v1, snapshot S1"):
            v1 = generate_test_data(4096, seed=10)
            s3.upload_object(test_bucket, key, v1)
            s1 = snapshots.create(test_bucket, source_prefix=prefix)

        with allure.step("Overwrite v2, snapshot S2"):
            v2 = generate_test_data(4096, seed=20)
            s3.upload_object(test_bucket, key, v2)
            s2 = snapshots.create(test_bucket, source_prefix=prefix)

        with allure.step("Overwrite v3 (current live state, no snapshot)"):
            v3 = generate_test_data(4096, seed=30)
            s3.upload_object(test_bucket, key, v3)

        with allure.step("Restore S1 — expect v1"):
            snapshots.restore(test_bucket, s1.snapshot_id)
            restored = s3.download_object(test_bucket, key)
            assert restored.checksum_sha256 == hashlib.sha256(v1).hexdigest()

        with allure.step("Restore S2 — expect v2"):
            snapshots.restore(test_bucket, s2.snapshot_id)
            restored = s3.download_object(test_bucket, key)
            assert restored.checksum_sha256 == hashlib.sha256(v2).hexdigest()

    @allure.story("A snapshot captures every object under its source prefix")
    @allure.severity(allure.severity_level.NORMAL)
    def test_snapshot_captures_multiple_objects_and_survives_deletion(
        self, s3: S3Client, snapshots: SnapshotService, test_bucket: str
    ):
        prefix = f"snap-batch/{uuid.uuid4().hex}"
        payloads = {f"{prefix}/obj-{i}.bin": generate_test_data(1024, seed=i) for i in range(5)}

        with allure.step("Write 5 objects under one prefix"):
            for key, data in payloads.items():
                assert s3.upload_object(test_bucket, key, data).succeeded

        with allure.step("Snapshot the whole prefix"):
            manifest = snapshots.create(test_bucket, source_prefix=prefix)
            assert manifest.object_count == 5

        with allure.step("Delete every live object"):
            for key in payloads:
                s3.delete_object(test_bucket, key)
            assert s3.list_objects(test_bucket, prefix=prefix) == []

        with allure.step("Restore — all 5 objects come back with correct checksums"):
            report = snapshots.restore(test_bucket, manifest.snapshot_id)
            assert report.passed
            assert len(report.restored_keys) == 5

            for key, data in payloads.items():
                restored = s3.download_object(test_bucket, key)
                assert restored.succeeded
                assert restored.checksum_sha256 == hashlib.sha256(data).hexdigest()

    @allure.story("Snapshotted data survives a node restart")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_restore_after_node_restart(
        self,
        s3: S3Client,
        snapshots: SnapshotService,
        chaos: ChaosController,
        test_bucket: str,
    ):
        prefix = f"snap-restart/{uuid.uuid4().hex}"
        key = f"{prefix}/data.bin"
        data = generate_test_data(32 * 1024, seed=77)

        with allure.step("Write baseline and snapshot it"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded
            manifest = snapshots.create(test_bucket, source_prefix=prefix)

        with allure.step("Cycle a MinIO node while the snapshot exists"):
            with chaos.node_stopped("storguard-minio3"):
                pass

        with allure.step("Overwrite live data after recovery"):
            s3.upload_object(test_bucket, key, generate_test_data(32 * 1024, seed=88))

        with allure.step("Restore the pre-restart snapshot"):
            report = snapshots.restore(test_bucket, manifest.snapshot_id)
            assert report.passed

        with allure.step("Verify restored checksum matches the pre-restart baseline"):
            restored = s3.download_object(test_bucket, key)
            assert restored.checksum_sha256 == upload.checksum_sha256

    @allure.story("Deleting a snapshot removes its stored objects and manifest")
    @allure.severity(allure.severity_level.NORMAL)
    def test_delete_snapshot_removes_objects(
        self, s3: S3Client, snapshots: SnapshotService, test_bucket: str
    ):
        prefix = f"snap-delete/{uuid.uuid4().hex}"
        key = f"{prefix}/data.bin"
        s3.upload_object(test_bucket, key, generate_test_data(1024, seed=5))

        with allure.step("Create then delete a snapshot"):
            manifest = snapshots.create(test_bucket, source_prefix=prefix)
            snapshots.delete(test_bucket, manifest.snapshot_id)

        with allure.step("Verify no objects remain under the snapshot's own prefix"):
            remaining = s3.list_objects(test_bucket, prefix=f".snapshots/{manifest.snapshot_id}/")
            assert remaining == []

        with allure.step("Verify it no longer appears in list()"):
            ids = [m.snapshot_id for m in snapshots.list(test_bucket)]
            assert manifest.snapshot_id not in ids

    @allure.story("list() returns every snapshot in creation order")
    @allure.severity(allure.severity_level.NORMAL)
    def test_list_returns_all_snapshots(
        self, s3: S3Client, snapshots: SnapshotService, test_bucket: str
    ):
        prefix = f"snap-list/{uuid.uuid4().hex}"
        key = f"{prefix}/data.bin"
        s3.upload_object(test_bucket, key, generate_test_data(1024, seed=1))

        with allure.step("Create three snapshots in sequence"):
            created_ids = [snapshots.create(test_bucket, source_prefix=prefix).snapshot_id for _ in range(3)]

        with allure.step("List and verify all three are present, oldest first"):
            listed = snapshots.list(test_bucket)
            listed_ids = [m.snapshot_id for m in listed if m.snapshot_id in created_ids]
            assert listed_ids == created_ids
            assert all(
                listed[i].created_at <= listed[i + 1].created_at for i in range(len(listed) - 1)
            )
