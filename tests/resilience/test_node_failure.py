"""Resilience tests — node failure, recovery and post-recovery data integrity."""

from __future__ import annotations

import time
import uuid

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.docker_client import DockerClient
from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import IntegrityValidator, generate_test_data
from storguard.models import FaultType


@allure.epic("Resilience")
@allure.feature("Node Failure")
@pytest.mark.resilience
class TestNodeFailure:

    @allure.story("Operations remain available when one node is down")
    @allure.title("Cluster serves reads during 1/4 node outage — EC:2 quorum holds")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_cluster_survives_single_node_stop(
        self,
        s3: S3Client,
        chaos: ChaosController,
        test_bucket: str,
    ):
        with allure.step("Upload 1 MB baseline object before fault injection"):
            key = f"resilience/{uuid.uuid4().hex}"
            data = generate_test_data(1024 * 1024)
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, f"Pre-fault upload failed: {upload.error}"

        with allure.step("Stop storguard-minio2 (1 of 4 nodes)"):
            with chaos.node_stopped("storguard-minio2") as timeline:

                with allure.step("Attach fault injection timestamp"):
                    allure.attach(
                        f"Node stopped at {timeline.fault_injected_at}",
                        name="fault-injection",
                        attachment_type=allure.attachment_type.TEXT,
                    )

                with allure.step("Read object while node is down — quorum must hold"):
                    read = s3.download_object(test_bucket, key)
                    assert read.succeeded, f"Read failed during node outage: {read.error}"

        with allure.step("Record cluster healthy timestamp after node restarts"):
            timeline.cluster_healthy_at = time.time()

        with allure.step("Verify post-recovery data integrity via SHA-256"):
            verify = s3.download_object(test_bucket, key)
            assert verify.succeeded
            assert verify.checksum_sha256 == upload.checksum_sha256, (
                "Data corrupted after node recovery"
            )
            timeline.integrity_verified_at = time.time()

        with allure.step("Attach recovery timeline summary"):
            allure.attach(
                f"Recovery time  : {timeline.recovery_time_seconds:.1f}s\n"
                f"Total downtime : {timeline.total_downtime_seconds:.1f}s",
                name="recovery-timeline",
                attachment_type=allure.attachment_type.TEXT,
            )

    @allure.story("Node restarts and cluster returns to full health")
    @allure.title("Stopped node restarts within 60s and reports running state")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_node_restart_recovery(
        self,
        s3: S3Client,
        chaos: ChaosController,
        docker_client: DockerClient,
        test_bucket: str,
    ):
        with allure.step("Stop storguard-minio3"):
            timeline = chaos.stop_node("storguard-minio3")

        try:
            with allure.step("Confirm storguard-minio3 is not running"):
                state = docker_client.get_state("storguard-minio3")
                assert not state.running, "Node should be stopped after chaos.stop_node()"

            with allure.step("Restart storguard-minio3"):
                chaos.restart_node("storguard-minio3")
                timeline.fault_removed_at = time.time()

            with allure.step("Wait up to 60s for node to become running"):
                started = docker_client.wait_until_running("storguard-minio3", deadline_seconds=60)
                assert started, "Node did not restart within 60 seconds"
                timeline.cluster_healthy_at = time.time()

        finally:
            with allure.step("Cleanup: restore_all() to guarantee no leaked faults"):
                chaos.restore_all()

        with allure.step("Attach recovery time summary"):
            allure.attach(
                f"Recovery time: {timeline.recovery_time_seconds}s",
                name="recovery-timeline",
                attachment_type=allure.attachment_type.TEXT,
            )
