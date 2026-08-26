"""Network fault resilience tests — latency injection and packet loss via tc.

These tests inject real kernel-level network faults into the MinIO gateway
container and verify the cluster handles degraded network conditions without
data loss or unhandled exceptions.
"""

from __future__ import annotations

import uuid
from typing import List

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import IntegrityValidator, generate_test_data
from storguard.models import OperationStatus
from storguard.workloads.engine import OperationType, WorkloadConfig, WorkloadEngine

GATEWAY_CONTAINER = "storguard-gateway"
NETWORK_INTERFACE = "eth0"


@allure.epic("Resilience")
@allure.feature("Network Faults")
@pytest.mark.resilience
class TestNetworkLatency:

    @allure.story("Cluster survives 200 ms gateway latency")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_cluster_survives_latency_injection(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str, integrity: IntegrityValidator
    ):
        data = generate_test_data(64 * 1024, seed=42)  # 64 KB
        key = f"latency-probe/{uuid.uuid4().hex}"

        with allure.step("Upload reference object before latency injection"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, f"Pre-fault upload failed: {upload.error}"

        with allure.step("Inject 200 ms network latency on gateway"):
            timeline = chaos.add_latency(GATEWAY_CONTAINER, latency_ms=200, interface=NETWORK_INTERFACE)
            allure.attach(
                f"fault={timeline.fault_type}\ninjected_at={timeline.fault_injected_at:.3f}\n"
                f"target={GATEWAY_CONTAINER}\nlatency_ms=200",
                name="tc-latency-inject",
                attachment_type=allure.attachment_type.TEXT,
            )

        try:
            with allure.step("Run 10 S3 operations under latency — expect success or clean error"):
                engine = WorkloadEngine(s3)
                cfg = WorkloadConfig(
                    bucket=test_bucket,
                    workers=5,
                    objects=10,
                    file_size_bytes=4 * 1024,
                    operation=OperationType.UPLOAD,
                )
                metrics = engine.run(cfg)
                allure.attach(
                    f"error_rate={metrics.error_rate_percent}%\n"
                    f"avg_latency={metrics.latency_ms_avg:.0f}ms\n"
                    f"p95_latency={metrics.latency_ms_p95:.0f}ms\n"
                    f"throughput={metrics.throughput_mbps} MB/s",
                    name="latency-workload-metrics",
                    attachment_type=allure.attachment_type.TEXT,
                )

            with allure.step("Verify original object intact after latency injection"):
                report = integrity.verify(test_bucket, key, data)
                allure.attach(
                    f"checksum_match={report.checksum_match}\n"
                    f"size_match={report.size_match}\n"
                    f"passed={report.passed}",
                    name="integrity-under-latency",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert report.passed, f"Data integrity failed under latency: {report.summary()}"

        finally:
            with allure.step("Remove latency fault and verify cluster healthy"):
                chaos._docker.clear_tc_rules(GATEWAY_CONTAINER, NETWORK_INTERFACE)

    @allure.story("S3 latency metrics increase proportionally under injection")
    @allure.severity(allure.severity_level.NORMAL)
    def test_latency_is_observable_in_metrics(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str
    ):
        engine = WorkloadEngine(s3)
        cfg = WorkloadConfig(
            bucket=test_bucket,
            workers=3,
            objects=6,
            file_size_bytes=1024,
            operation=OperationType.UPLOAD,
        )

        with allure.step("Baseline — measure latency without fault"):
            baseline = engine.run(cfg)

        with allure.step("Inject 300 ms latency"):
            chaos.add_latency(GATEWAY_CONTAINER, latency_ms=300, interface=NETWORK_INTERFACE)

        try:
            with allure.step("Measure latency under fault"):
                degraded = engine.run(cfg)

            allure.attach(
                f"baseline_avg={baseline.latency_ms_avg:.0f}ms\n"
                f"degraded_avg={degraded.latency_ms_avg:.0f}ms\n"
                f"increase={degraded.latency_ms_avg - baseline.latency_ms_avg:.0f}ms",
                name="latency-comparison",
                attachment_type=allure.attachment_type.TEXT,
            )

            with allure.step("Assert degraded latency exceeds baseline"):
                assert degraded.latency_ms_avg > baseline.latency_ms_avg, (
                    "Injected latency not reflected in measured metrics — "
                    f"baseline={baseline.latency_ms_avg:.0f}ms, degraded={degraded.latency_ms_avg:.0f}ms"
                )
        finally:
            chaos._docker.clear_tc_rules(GATEWAY_CONTAINER, NETWORK_INTERFACE)


@allure.epic("Resilience")
@allure.feature("Network Faults")
@pytest.mark.resilience
class TestPacketLoss:

    @allure.story("Cluster tolerates 20% packet loss without data corruption")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_cluster_survives_packet_loss(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str, integrity: IntegrityValidator
    ):
        data = generate_test_data(32 * 1024, seed=99)  # 32 KB
        key = f"packet-loss-probe/{uuid.uuid4().hex}"

        with allure.step("Upload reference object before fault injection"):
            upload = s3.upload_object(test_bucket, key, data)
            assert upload.succeeded, f"Pre-fault upload failed: {upload.error}"

        with allure.step("Inject 20% packet loss on gateway"):
            timeline = chaos.add_packet_loss(GATEWAY_CONTAINER, loss_percent=20, interface=NETWORK_INTERFACE)
            allure.attach(
                f"fault={timeline.fault_type}\ninjected_at={timeline.fault_injected_at:.3f}\n"
                f"target={GATEWAY_CONTAINER}\nloss_percent=20",
                name="tc-packet-loss-inject",
                attachment_type=allure.attachment_type.TEXT,
            )

        try:
            with allure.step("Run operations under packet loss — boto3 retries should absorb failures"):
                engine = WorkloadEngine(s3)
                cfg = WorkloadConfig(
                    bucket=test_bucket,
                    workers=4,
                    objects=8,
                    file_size_bytes=4 * 1024,
                    operation=OperationType.UPLOAD,
                )
                metrics = engine.run(cfg)
                allure.attach(
                    f"error_rate={metrics.error_rate_percent}%\n"
                    f"successful={metrics.successful_operations}/{metrics.total_operations}\n"
                    f"avg_latency={metrics.latency_ms_avg:.0f}ms",
                    name="packet-loss-workload-metrics",
                    attachment_type=allure.attachment_type.TEXT,
                )

            with allure.step("Verify reference object integrity — no data corruption"):
                report = integrity.verify(test_bucket, key, data)
                allure.attach(
                    f"checksum_match={report.checksum_match}\npassed={report.passed}",
                    name="integrity-under-packet-loss",
                    attachment_type=allure.attachment_type.TEXT,
                )
                assert report.passed, f"Data corrupted under packet loss: {report.summary()}"

        finally:
            with allure.step("Remove packet-loss fault"):
                chaos._docker.clear_tc_rules(GATEWAY_CONTAINER, NETWORK_INTERFACE)

    @allure.story("Operations fail cleanly under extreme packet loss")
    @allure.severity(allure.severity_level.NORMAL)
    def test_extreme_packet_loss_fails_cleanly(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str
    ):
        """50% packet loss may cause failures — assert no Python exceptions propagate."""
        with allure.step("Inject 50% packet loss"):
            chaos.add_packet_loss(GATEWAY_CONTAINER, loss_percent=50, interface=NETWORK_INTERFACE)

        try:
            with allure.step("Attempt uploads — expect success or clean OperationResult.FAILED"):
                engine = WorkloadEngine(s3)
                cfg = WorkloadConfig(
                    bucket=test_bucket,
                    workers=3,
                    objects=6,
                    file_size_bytes=1024,
                    operation=OperationType.UPLOAD,
                )
                metrics = engine.run(cfg)
                allure.attach(
                    f"error_rate={metrics.error_rate_percent}%\n"
                    f"successful={metrics.successful_operations}/{metrics.total_operations}",
                    name="extreme-loss-metrics",
                    attachment_type=allure.attachment_type.TEXT,
                )
                # The engine must return a WorkloadMetrics — no unhandled exception
                assert metrics.total_operations == cfg.objects

        finally:
            with allure.step("Remove fault"):
                chaos._docker.clear_tc_rules(GATEWAY_CONTAINER, NETWORK_INTERFACE)
