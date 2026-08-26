"""Performance tests — concurrent workloads, throughput and latency percentiles."""

from __future__ import annotations

import allure
import pytest

from storguard.clients.s3_client import S3Client
from storguard.quality_gate.gate import GateThresholds, QualityGate
from storguard.workloads.engine import OperationType, WorkloadConfig, WorkloadEngine


@allure.epic("Performance")
@allure.feature("Workload Engine")
@pytest.mark.performance
class TestWorkloadEngine:

    @allure.story("Concurrent upload throughput")
    @allure.title("10 workers uploading 20 × 1 MB objects maintain < 5% error rate")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_concurrent_uploads(self, s3: S3Client, test_bucket: str):
        with allure.step("Configure workload: 10 workers, 20 objects, 1 MB each, UPLOAD"):
            engine = WorkloadEngine(s3)
            config = WorkloadConfig(
                bucket=test_bucket,
                workers=10,
                objects=20,
                file_size_bytes=1024 * 1024,
                operation=OperationType.UPLOAD,
            )

        with allure.step("Execute concurrent workload"):
            metrics = engine.run(config)

        with allure.step("Attach workload metrics as Allure artifact"):
            allure.attach(
                f"Operations : {metrics.total_operations}\n"
                f"Successful : {metrics.successful_operations}\n"
                f"Error rate : {metrics.error_rate_percent:.1f}%\n"
                f"Throughput : {metrics.throughput_mbps:.1f} MB/s\n"
                f"Avg latency: {metrics.latency_ms_avg:.0f} ms\n"
                f"P95 latency: {metrics.latency_ms_p95:.0f} ms\n"
                f"P99 latency: {metrics.latency_ms_p99:.0f} ms",
                name="workload-metrics",
                attachment_type=allure.attachment_type.TEXT,
            )

        with allure.step("Assert error_rate < 5% and at least one successful operation"):
            assert metrics.error_rate_percent < 5.0, (
                f"Error rate too high: {metrics.error_rate_percent}%"
            )
            assert metrics.successful_operations > 0

    @allure.story("Quality gate evaluation after workload")
    @allure.title("Mixed CRUD workload passes quality gate thresholds")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_workload_meets_quality_gate(self, s3: S3Client, test_bucket: str):
        with allure.step("Configure workload: 5 workers, 10 objects, 1 KB, MIXED"):
            engine = WorkloadEngine(s3)
            config = WorkloadConfig(
                bucket=test_bucket,
                workers=5,
                objects=10,
                file_size_bytes=1024,
                operation=OperationType.MIXED,
            )

        with allure.step("Execute workload"):
            metrics = engine.run(config)

        with allure.step("Configure quality gate: error_rate<5%, p95<2000ms (relaxed for local env)"):
            gate = QualityGate(GateThresholds(
                maximum_error_rate_percent=5.0,
                maximum_p95_latency_ms=2000.0,
            ))

        with allure.step("Evaluate quality gate against workload metrics"):
            result = gate.evaluate(metrics)

        with allure.step("Attach gate violations if any"):
            if result.violations:
                allure.attach(
                    "\n".join(result.violations),
                    name="gate-violations",
                    attachment_type=allure.attachment_type.TEXT,
                )

        with allure.step("Assert gate passed"):
            assert result.passed, f"Gate failed: {result.violations}"
