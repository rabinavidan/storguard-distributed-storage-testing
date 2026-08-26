"""Shared typed result models used across the entire StorGuard platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class OperationStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"


class FailureCategory(str, Enum):
    DNS_RESOLUTION_FAILED = "DNS_RESOLUTION_FAILED"
    TCP_CONNECTION_REFUSED = "TCP_CONNECTION_REFUSED"
    TCP_CONNECTION_TIMEOUT = "TCP_CONNECTION_TIMEOUT"
    TLS_HANDSHAKE_FAILED = "TLS_HANDSHAKE_FAILED"
    HTTP_AUTHENTICATION_FAILED = "HTTP_AUTHENTICATION_FAILED"
    S3_SERVICE_UNAVAILABLE = "S3_SERVICE_UNAVAILABLE"
    STORAGE_OPERATION_TIMEOUT = "STORAGE_OPERATION_TIMEOUT"
    DATA_INTEGRITY_FAILED = "DATA_INTEGRITY_FAILED"


class FaultType(str, Enum):
    NODE_STOP = "node_stop"
    NODE_RESTART = "node_restart"
    NETWORK_LATENCY = "network_latency"
    PACKET_LOSS = "packet_loss"
    DISK_PRESSURE = "disk_pressure"
    CPU_LIMIT = "cpu_limit"
    MEMORY_LIMIT = "memory_limit"


@dataclass
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class OperationResult:
    status: OperationStatus
    duration_ms: float
    bucket: str
    key: str
    size_bytes: int = 0
    checksum_sha256: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status == OperationStatus.SUCCESS


@dataclass
class LayerTiming:
    layer: str
    duration_ms: float
    succeeded: bool
    detail: Optional[str] = None


@dataclass
class ConnectivityResult:
    endpoint: str
    overall_success: bool
    failure_category: Optional[FailureCategory]
    layer_timings: List[LayerTiming] = field(default_factory=list)
    total_duration_ms: float = 0.0


@dataclass
class WorkloadMetrics:
    total_operations: int
    successful_operations: int
    failed_operations: int
    duration_seconds: float
    throughput_mbps: float
    latency_ms_min: float
    latency_ms_avg: float
    latency_ms_max: float
    latency_ms_p95: float
    latency_ms_p99: float
    error_rate_percent: float


@dataclass
class RecoveryTimeline:
    fault_injected_at: float          # epoch seconds
    fault_type: FaultType
    fault_removed_at: Optional[float] = None
    cluster_healthy_at: Optional[float] = None
    integrity_verified_at: Optional[float] = None

    @property
    def recovery_time_seconds(self) -> Optional[float]:
        if self.cluster_healthy_at and self.fault_removed_at:
            return self.cluster_healthy_at - self.fault_removed_at
        return None

    @property
    def total_downtime_seconds(self) -> Optional[float]:
        if self.cluster_healthy_at:
            return self.cluster_healthy_at - self.fault_injected_at
        return None


@dataclass
class GateResult:
    passed: bool
    metrics: WorkloadMetrics
    violations: List[str] = field(default_factory=list)
    recovery_timeline: Optional[RecoveryTimeline] = None
