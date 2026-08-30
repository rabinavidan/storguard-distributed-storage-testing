"""Primary -> secondary async replication worker.

Not a MinIO feature — MinIO's own site replication needs two clustered
deployments and admin bootstrapping that don't fit a local test lab. This is a
small Python worker standing in for a real replication engine, so replication
lag, failover reads and the recovery-point (data-loss) window can all be
exercised in tests against two independent, real S3 endpoints.

Nothing here is trusted implicitly: sync_once() reads each object straight back
off the secondary is left to the caller (see tests/replication), matching the
project's convention of re-verifying checksums rather than trusting a
successful call.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from storguard.clients.s3_client import S3Client


@dataclass
class ReplicationStatus:
    replicated_keys: List[str] = field(default_factory=list)
    failed_keys: List[str] = field(default_factory=list)
    last_sync_at: float = 0.0
    lag_seconds: float = 0.0


class ReplicationWorker:
    def __init__(self, primary: S3Client, secondary: S3Client, bucket: str, prefix: str = "") -> None:
        self._primary = primary
        self._secondary = secondary
        self._bucket = bucket
        self._prefix = prefix
        self._replicated_checksums: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def sync_once(self) -> ReplicationStatus:
        """Copy every primary object not yet replicated (by checksum) to the
        secondary. Safe to call repeatedly — already-replicated, unchanged
        objects are skipped."""
        start = time.time()
        status = ReplicationStatus(last_sync_at=start)

        for key in self._primary.list_objects(self._bucket, prefix=self._prefix):
            meta = self._primary.get_object_metadata(self._bucket, key)
            checksum = meta["metadata"].get("sha256")

            with self._lock:
                if checksum and self._replicated_checksums.get(key) == checksum:
                    continue

            data = self._primary.download_bytes(self._bucket, key)
            if data is None:
                status.failed_keys.append(key)
                continue

            upload = self._secondary.upload_object(self._bucket, key, data)
            if upload.succeeded:
                with self._lock:
                    self._replicated_checksums[key] = checksum or upload.checksum_sha256 or ""
                status.replicated_keys.append(key)
            else:
                status.failed_keys.append(key)

        status.lag_seconds = time.time() - start
        return status

    def is_replicated(self, key: str, checksum: str) -> bool:
        with self._lock:
            return self._replicated_checksums.get(key) == checksum

    # ─── Optional background loop ─────────────────────────────────────────────

    def start(self, interval_seconds: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                self.sync_once()
                self._stop.wait(interval_seconds)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
