"""Configurable concurrent workload engine — parallel S3 operations with metric capture."""

import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List

from storguard.clients.s3_client import S3Client
from storguard.integrity.validator import generate_test_data
from storguard.models import OperationResult, OperationStatus, WorkloadMetrics


class OperationType(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE = "delete"
    MIXED = "mixed"


@dataclass
class WorkloadConfig:
    bucket: str
    workers: int = 10
    objects: int = 50
    file_size_bytes: int = 1024 * 1024   # 1 MB default
    operation: OperationType = OperationType.MIXED
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex[:8]


class WorkloadEngine:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    def run(self, config: WorkloadConfig) -> WorkloadMetrics:
        data = generate_test_data(config.file_size_bytes)
        keys = [f"workload/{config.run_id}/obj-{i:05d}" for i in range(config.objects)]

        results: List[OperationResult] = []
        start = time.monotonic()

        with ThreadPoolExecutor(max_workers=config.workers) as pool:
            futures = {
                pool.submit(self._execute_one, config, key, data, i): key
                for i, key in enumerate(keys)
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        OperationResult(
                            status=OperationStatus.FAILED,
                            duration_ms=0,
                            bucket=config.bucket,
                            key=futures[future],
                            error=str(exc),
                        )
                    )

        elapsed = time.monotonic() - start
        return _compute_metrics(results, elapsed, config.file_size_bytes)

    def _execute_one(
        self, config: WorkloadConfig, key: str, data: bytes, index: int
    ) -> OperationResult:
        if config.operation == OperationType.UPLOAD:
            return self._s3.upload_object(config.bucket, key, data)
        elif config.operation == OperationType.DOWNLOAD:
            return self._s3.download_object(config.bucket, key)
        elif config.operation == OperationType.DELETE:
            return self._s3.delete_object(config.bucket, key)
        else:  # MIXED: write, read back, delete every 5th
            upload = self._s3.upload_object(config.bucket, key, data)
            if not upload.succeeded:
                return upload
            self._s3.download_object(config.bucket, key)
            if index % 5 == 0:
                self._s3.delete_object(config.bucket, key)
            return upload


def _compute_metrics(
    results: List[OperationResult], elapsed_seconds: float, file_size_bytes: int
) -> WorkloadMetrics:
    successful = [r for r in results if r.succeeded]
    failed = [r for r in results if not r.succeeded]
    latencies = sorted(r.duration_ms for r in successful)

    total_bytes = len(successful) * file_size_bytes
    throughput_mbps = (total_bytes / (1024 * 1024)) / elapsed_seconds if elapsed_seconds else 0

    def percentile(data: List[float], p: float) -> float:
        if not data:
            return 0.0
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    return WorkloadMetrics(
        total_operations=len(results),
        successful_operations=len(successful),
        failed_operations=len(failed),
        duration_seconds=elapsed_seconds,
        throughput_mbps=round(throughput_mbps, 2),
        latency_ms_min=min(latencies) if latencies else 0,
        latency_ms_avg=round(statistics.mean(latencies), 2) if latencies else 0,
        latency_ms_max=max(latencies) if latencies else 0,
        latency_ms_p95=round(percentile(latencies, 95), 2),
        latency_ms_p99=round(percentile(latencies, 99), 2),
        error_rate_percent=round(len(failed) / len(results) * 100, 2) if results else 0,
    )
