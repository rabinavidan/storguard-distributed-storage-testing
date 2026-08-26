"""Unit tests for shared models — no external dependencies required."""

from __future__ import annotations

import allure
import pytest

from storguard.models import (
    CommandResult,
    FaultType,
    GateResult,
    OperationResult,
    OperationStatus,
    RecoveryTimeline,
    WorkloadMetrics,
)


def _workload_metrics() -> WorkloadMetrics:
    return WorkloadMetrics(
        total_operations=100,
        successful_operations=99,
        failed_operations=1,
        duration_seconds=10.0,
        throughput_mbps=5.0,
        latency_ms_min=10.0,
        latency_ms_avg=50.0,
        latency_ms_max=200.0,
        latency_ms_p95=180.0,
        latency_ms_p99=195.0,
        error_rate_percent=1.0,
    )


@allure.epic("Models")
@allure.feature("CommandResult")
@pytest.mark.unit
class TestCommandResult:

    @allure.story("Success determination")
    @allure.title("succeeded=True when exit_code is 0 and not timed out")
    def test_succeeded_when_exit_code_zero(self):
        with allure.step("Instantiate CommandResult with exit_code=0"):
            r = CommandResult("ls", "output", "", 0, 12.5)
        with allure.step("Assert succeeded is True"):
            assert r.succeeded is True

    @allure.story("Failure determination")
    @allure.title("succeeded=False when exit_code is non-zero")
    def test_failed_when_nonzero_exit_code(self):
        with allure.step("Instantiate CommandResult with exit_code=127"):
            r = CommandResult("bad-cmd", "", "not found", 127, 5.0)
        with allure.step("Assert succeeded is False"):
            assert r.succeeded is False

    @allure.story("Failure determination")
    @allure.title("succeeded=False when timed_out=True even with exit_code=0")
    def test_failed_when_timed_out(self):
        with allure.step("Instantiate CommandResult with timed_out=True"):
            r = CommandResult("sleep 99", "", "", 0, 30000.0, timed_out=True)
        with allure.step("Assert succeeded is False (timeout overrides exit code)"):
            assert r.succeeded is False


@allure.epic("Models")
@allure.feature("OperationResult")
@pytest.mark.unit
class TestOperationResult:

    @allure.story("Success determination")
    @allure.title("succeeded=True when status is SUCCESS")
    def test_succeeded_on_success_status(self):
        with allure.step("Instantiate OperationResult with SUCCESS status"):
            r = OperationResult(OperationStatus.SUCCESS, 42.0, "bucket", "key")
        with allure.step("Assert succeeded is True"):
            assert r.succeeded is True

    @allure.story("Failure determination")
    @allure.title("succeeded=False when status is FAILED")
    def test_failed_on_error_status(self):
        with allure.step("Instantiate OperationResult with FAILED status"):
            r = OperationResult(OperationStatus.FAILED, 10.0, "bucket", "key", error="boom")
        with allure.step("Assert succeeded is False"):
            assert r.succeeded is False


@allure.epic("Models")
@allure.feature("RecoveryTimeline")
@pytest.mark.unit
class TestRecoveryTimeline:

    @allure.story("Recovery time calculation")
    @allure.title("recovery_time = cluster_healthy_at - fault_removed_at")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_recovery_time_calculated_correctly(self):
        with allure.step("Build timeline: fault_removed=T+10, cluster_healthy=T+25"):
            timeline = RecoveryTimeline(
                fault_injected_at=1000.0,
                fault_type=FaultType.NODE_STOP,
                fault_removed_at=1010.0,
                cluster_healthy_at=1025.0,
            )
        with allure.step("Assert recovery_time_seconds == 15.0"):
            assert timeline.recovery_time_seconds == pytest.approx(15.0)

    @allure.story("Recovery time calculation")
    @allure.title("recovery_time_seconds is None when fault was never removed")
    def test_recovery_time_none_when_not_restored(self):
        with allure.step("Build timeline without fault_removed_at"):
            timeline = RecoveryTimeline(fault_injected_at=1000.0, fault_type=FaultType.NODE_STOP)
        with allure.step("Assert recovery_time_seconds is None"):
            assert timeline.recovery_time_seconds is None

    @allure.story("Total downtime calculation")
    @allure.title("total_downtime_seconds = cluster_healthy_at - fault_injected_at")
    def test_total_downtime_includes_injection_period(self):
        with allure.step("Build timeline: fault injected at T+0, cluster healthy at T+45"):
            timeline = RecoveryTimeline(
                fault_injected_at=1000.0,
                fault_type=FaultType.NETWORK_LATENCY,
                cluster_healthy_at=1045.0,
            )
        with allure.step("Assert total_downtime_seconds == 45.0"):
            assert timeline.total_downtime_seconds == pytest.approx(45.0)


@allure.epic("Models")
@allure.feature("GateResult")
@pytest.mark.unit
class TestGateResult:

    @allure.story("Pass/fail determination")
    @allure.title("passed=True and violations empty when gate passes")
    def test_passed_when_no_violations(self):
        with allure.step("Build GateResult with passed=True and no violations"):
            gate = GateResult(passed=True, metrics=_workload_metrics())
        with allure.step("Assert passed=True and violations is empty"):
            assert gate.passed is True
            assert gate.violations == []

    @allure.story("Pass/fail determination")
    @allure.title("passed=False and violations list populated when gate fails")
    def test_failed_when_violations_present(self):
        with allure.step("Build GateResult with one violation"):
            gate = GateResult(
                passed=False,
                metrics=_workload_metrics(),
                violations=["error_rate 5.2% > 2%"],
            )
        with allure.step("Assert passed=False and violations has 1 item"):
            assert gate.passed is False
            assert len(gate.violations) == 1
