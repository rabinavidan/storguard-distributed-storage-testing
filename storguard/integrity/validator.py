"""Data integrity validator — SHA-256 round-trip verification after upload, chaos and recovery."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from storguard.clients.s3_client import S3Client
from storguard.models import OperationResult, OperationStatus


@dataclass
class IntegrityReport:
    bucket: str
    key: str
    size_bytes: int
    original_sha256: str
    retrieved_sha256: Optional[str]
    size_match: bool
    checksum_match: bool

    @property
    def passed(self) -> bool:
        return self.size_match and self.checksum_match

    def summary(self) -> str:
        if self.passed:
            return f"PASS {self.key} ({self.size_bytes} bytes, sha256={self.original_sha256[:12]}...)"
        details = []
        if not self.size_match:
            details.append("size mismatch")
        if not self.checksum_match:
            details.append(f"sha256 mismatch: expected {self.original_sha256[:12]}... got {str(self.retrieved_sha256)[:12]}...")
        return f"FAIL {self.key}: {', '.join(details)}"


class IntegrityValidator:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    def verify(self, bucket: str, key: str, original_data: bytes) -> IntegrityReport:
        original_sha256 = hashlib.sha256(original_data).hexdigest()
        result = self._s3.download_object(bucket, key)

        if not result.succeeded:
            return IntegrityReport(
                bucket=bucket,
                key=key,
                size_bytes=len(original_data),
                original_sha256=original_sha256,
                retrieved_sha256=None,
                size_match=False,
                checksum_match=False,
            )

        return IntegrityReport(
            bucket=bucket,
            key=key,
            size_bytes=len(original_data),
            original_sha256=original_sha256,
            retrieved_sha256=result.checksum_sha256,
            size_match=result.size_bytes == len(original_data),
            checksum_match=result.checksum_sha256 == original_sha256,
        )

    def verify_batch(
        self, bucket: str, objects: Dict[str, bytes]
    ) -> List[IntegrityReport]:
        return [self.verify(bucket, key, data) for key, data in objects.items()]

    def all_passed(self, reports: List[IntegrityReport]) -> bool:
        return all(r.passed for r in reports)

    def corruption_count(self, reports: List[IntegrityReport]) -> int:
        return sum(1 for r in reports if not r.passed)


def generate_test_data(size_bytes: int, seed: int = 0) -> bytes:
    """Generate deterministic test payload of exact size."""
    if size_bytes == 0:
        return b""
    rng = bytearray()
    pattern = f"storguard-seed{seed}-".encode()
    while len(rng) < size_bytes:
        rng.extend(pattern)
    return bytes(rng[:size_bytes])
