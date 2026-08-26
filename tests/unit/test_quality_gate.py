"""Unit tests for quality gate threshold evaluation."""

from __future__ import annotations

import allure
import pytest

from storguard.models import FaultType, RecoveryTimeline, WorkloadMetrics
from storguard.quality_gate.gate import GateThresholds, QualityGate


def _metrics(**overrides) -> WorkloadMetrics:
    base = dict(
        total_operations=100,
        successful_operations=99,
        failed_operations=1,
        duration_seconds=10.0,
        throughput_mbps=5.0,
        latency_ms_min=10.0,
        latency_ms_avg=50.0,
        latency_ms_max=200.0,
        latency_ms_p95=400.0,
        latency_ms_p99=600.0,
        error_rate_percent=1.0,
    )
    base.update(overrides)
    return WorkloadMetrics(**base)


@allure.epic("Quality Gate")
@allure.feature("Threshold Evaluation")
@pytest.mark.unit
class TestQualityGate:

    def setup_method(self):
        self.gate = QualityGate(GateThresholds())

    @allure.story("Pass conditions")
    @allure.title("Gate passes when all metrics are within thresholds")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_passes_within_all_thresholds(self):
        with allure.step("Build metrics well within all default thresholds"):
            metrics = _metrics()

        with allure.step("Evaluate gate"):
            result = self.gate.evaluate(metrics)

        with allure.step("Assert passed=True and no violations"):
            assert result.passed is True
            assert result.violations == []

    @allure.story("Error rate violation")
    @allure.title("Gate fails when error_rate_percent exceeds threshold (3.5% > 2%)")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_fails_on_high_error_rate(self):
        with allure.step("Build metrics with error_rate=3.5% (above 2% threshold)"):
            metrics = _metrics(error_rate_percent=3.5)

        with allure.step("Evaluate gate"):
            result = self.gate.evaluate(metrics)

        with allure.step("Assert failed and 'error_rate' in violations"):
            assert result.passed is False
            assert any("error_rate" in v for v in result.violations)

    @allure.story("Latency violation")
    @allure.title("Gate fails when P95 latency exceeds threshold (900ms > 800ms)")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_fails_on_p95_latency_exceeded(self):
        with allure.step("Build metrics with p95_latency=900ms (above 800ms threshold)"):
            metrics = _metrics(latency_ms_p95=900.0)

        with allure.step("Evaluate gate"):
            result = self.gate.evaluate(metrics)

        with allure.step("Assert failed and 'p95_latency' in violations"):
            assert result.passed is False
            assert any("p95_latency" in v for v in result.violations)

    @allure.story("Data integrity violation")
    @allure.title("Gate fails immediately on any data corruption (0 tolerance)")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_fails_on_data_corruption(self):
        with allure.step("Build metrics with corruption_count=1"):
            metrics = _metrics()

        with allure.step("Evaluate gate with corruption_count=1"):
            result = self.gate.evaluate(metrics, corruption_count=1)

        with allure.step("Assert failed and 'data_corruption' in violations"):
            assert result.passed is False
            assert any("data_corruption" in v for v in result.violations)

    @allure.story("Recovery time violation")
    @allure.title("Gate fails when recovery takes longer than threshold (45s > 30s)")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_fails_on_slow_recovery(self):
        with allure.step("Build RecoveryTimeline: 10s fault + 35s to healthy = 45s total"):
            timeline = RecoveryTimeline(
                fault_injected_at=1000.0,
                fault_type=FaultType.NODE_STOP,
                fault_removed_at=1010.0,
                cluster_healthy_at=1055.0,
            )

        with allure.step("Evaluate gate with slow recovery timeline"):
            result = self.gate.evaluate(_metrics(), recovery=timeline)

        with allure.step("Assert failed and 'recovery_time' in violations"):
            assert result.passed is False
            assert any("recovery_time" in v for v in result.violations)

    @allure.story("Performance regression")
    @allure.title("Gate fails when avg latency regresses > 20% vs baseline")
    @allure.severity(allure.severity_level.NORMAL)
    def test_fails_on_performance_regression(self):
        with allure.step("Build baseline (avg=50ms) and current (avg=70ms → 40% regression)"):
            baseline = _metrics(latency_ms_avg=50.0)
            current = _metrics(latency_ms_avg=70.0)

        with allure.step("Evaluate gate with baseline comparison"):
            result = self.gate.evaluate(current, baseline=baseline)

        with allure.step("Assert failed and 'regression' in violations"):
            assert result.passed is False
            assert any("regression" in v for v in result.violations)

    @allure.story("Pass conditions")
    @allure.title("Zero corruption is explicitly allowed (corruption_count=0 passes)")
    def test_zero_corruption_allowed(self):
        with allure.step("Evaluate gate with corruption_count=0"):
            result = self.gate.evaluate(_metrics(), corruption_count=0)

        with allure.step("Assert passed=True"):
            assert result.passed is True

    @allure.story("Multiple violations")
    @allure.title("All active violations are reported simultaneously, not short-circuited")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_multiple_violations_all_reported(self):
        with allure.step("Build metrics with error_rate=5% AND p95=1000ms AND corruption=2"):
            metrics = _metrics(error_rate_percent=5.0, latency_ms_p95=1000.0)

        with allure.step("Evaluate gate with corruption_count=2"):
            result = self.gate.evaluate(metrics, corruption_count=2)

        with allure.step("Assert failed and exactly 3 violations reported"):
            assert result.passed is False
            assert len(result.violations) == 3
