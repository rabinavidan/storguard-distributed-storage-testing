"""Quality gate — evaluates workload metrics against configured thresholds."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from storguard.models import GateResult, RecoveryTimeline, WorkloadMetrics


@dataclass
class GateThresholds:
    maximum_error_rate_percent: float = 2.0
    maximum_data_corruption_count: int = 0
    maximum_recovery_time_seconds: float = 30.0
    maximum_p95_latency_ms: float = 800.0
    maximum_performance_regression_percent: float = 20.0

    @classmethod
    def from_dict(cls, data: dict) -> "GateThresholds":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class QualityGate:
    def __init__(self, thresholds: GateThresholds) -> None:
        self._t = thresholds

    def evaluate(
        self,
        metrics: WorkloadMetrics,
        corruption_count: int = 0,
        recovery: Optional[RecoveryTimeline] = None,
        baseline: Optional[WorkloadMetrics] = None,
    ) -> GateResult:
        violations: List[str] = []

        if metrics.error_rate_percent > self._t.maximum_error_rate_percent:
            violations.append(
                f"error_rate {metrics.error_rate_percent:.1f}% > {self._t.maximum_error_rate_percent}%"
            )

        if corruption_count > self._t.maximum_data_corruption_count:
            violations.append(
                f"data_corruption {corruption_count} > {self._t.maximum_data_corruption_count}"
            )

        if metrics.latency_ms_p95 > self._t.maximum_p95_latency_ms:
            violations.append(
                f"p95_latency {metrics.latency_ms_p95:.0f}ms > {self._t.maximum_p95_latency_ms:.0f}ms"
            )

        if recovery and recovery.recovery_time_seconds is not None:
            if recovery.recovery_time_seconds > self._t.maximum_recovery_time_seconds:
                violations.append(
                    f"recovery_time {recovery.recovery_time_seconds:.1f}s > {self._t.maximum_recovery_time_seconds}s"
                )

        if baseline:
            regression = (
                (metrics.latency_ms_avg - baseline.latency_ms_avg) / baseline.latency_ms_avg * 100
                if baseline.latency_ms_avg > 0
                else 0
            )
            if regression > self._t.maximum_performance_regression_percent:
                violations.append(
                    f"performance_regression {regression:.1f}% > {self._t.maximum_performance_regression_percent}%"
                )

        return GateResult(
            passed=len(violations) == 0,
            metrics=metrics,
            violations=violations,
            recovery_timeline=recovery,
        )

    def save_baseline(self, metrics: WorkloadMetrics, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metrics.__dict__, indent=2))

    def load_baseline(self, path: Path) -> Optional[WorkloadMetrics]:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return WorkloadMetrics(**data)
