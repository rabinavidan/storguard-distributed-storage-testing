"""Point-in-time snapshot service — create/list/restore/delete via server-side S3 copy.

A snapshot is a server-side copy of every live object under a source prefix into a
`.snapshots/<snapshot_id>/` namespace in the same bucket, plus a JSON manifest
recording which relative keys were captured and their SHA-256 checksums (carried
over for free — copy_object() preserves the sha256 metadata written on upload).
Restore copies the snapshotted objects back over the live prefix and re-verifies
every checksum; nothing is trusted just because the copy call reported success.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List

from storguard.clients.s3_client import S3Client

SNAPSHOT_PREFIX = ".snapshots"
MANIFEST_KEY = "_manifest.json"


@dataclass
class SnapshotManifest:
    snapshot_id: str
    bucket: str
    source_prefix: str
    created_at: float
    objects: Dict[str, str] = field(default_factory=dict)  # relative key -> sha256

    @property
    def object_count(self) -> int:
        return len(self.objects)

    def to_json(self) -> str:
        return json.dumps(
            {
                "snapshot_id": self.snapshot_id,
                "bucket": self.bucket,
                "source_prefix": self.source_prefix,
                "created_at": self.created_at,
                "objects": self.objects,
            }
        )

    @classmethod
    def from_json(cls, raw: bytes) -> "SnapshotManifest":
        payload = json.loads(raw)
        return cls(
            snapshot_id=payload["snapshot_id"],
            bucket=payload["bucket"],
            source_prefix=payload["source_prefix"],
            created_at=payload["created_at"],
            objects=payload["objects"],
        )


@dataclass
class RestoreReport:
    snapshot_id: str
    restored_keys: List[str] = field(default_factory=list)
    failed_keys: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.restored_keys) and not self.failed_keys


class SnapshotService:
    def __init__(self, s3: S3Client) -> None:
        self._s3 = s3

    def create(self, bucket: str, source_prefix: str = "") -> SnapshotManifest:
        snapshot_id = uuid.uuid4().hex[:12]
        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            bucket=bucket,
            source_prefix=source_prefix,
            created_at=time.time(),
        )

        for key in self._s3.list_objects(bucket, prefix=source_prefix):
            relative_key = key[len(source_prefix):].lstrip("/") if source_prefix else key
            snap_key = f"{SNAPSHOT_PREFIX}/{snapshot_id}/{relative_key}"
            copy = self._s3.copy_object(bucket, key, bucket, snap_key)
            if not copy.succeeded:
                raise RuntimeError(f"Snapshot copy failed for {key}: {copy.error}")
            manifest.objects[relative_key] = copy.checksum_sha256 or ""

        upload = self._s3.upload_object(
            bucket,
            f"{SNAPSHOT_PREFIX}/{snapshot_id}/{MANIFEST_KEY}",
            manifest.to_json().encode("utf-8"),
            content_type="application/json",
        )
        if not upload.succeeded:
            raise RuntimeError(f"Snapshot manifest write failed: {upload.error}")
        return manifest

    def list(self, bucket: str) -> List[SnapshotManifest]:
        manifests: List[SnapshotManifest] = []
        for key in self._s3.list_objects(bucket, prefix=f"{SNAPSHOT_PREFIX}/"):
            if not key.endswith(MANIFEST_KEY):
                continue
            raw = self._s3.download_bytes(bucket, key)
            if raw is not None:
                manifests.append(SnapshotManifest.from_json(raw))
        return sorted(manifests, key=lambda m: m.created_at)

    def get(self, bucket: str, snapshot_id: str) -> SnapshotManifest:
        raw = self._s3.download_bytes(bucket, f"{SNAPSHOT_PREFIX}/{snapshot_id}/{MANIFEST_KEY}")
        if raw is None:
            raise ValueError(f"Snapshot '{snapshot_id}' not found in bucket '{bucket}'")
        return SnapshotManifest.from_json(raw)

    def restore(self, bucket: str, snapshot_id: str) -> RestoreReport:
        manifest = self.get(bucket, snapshot_id)
        report = RestoreReport(snapshot_id=snapshot_id)

        for relative_key, expected_checksum in manifest.objects.items():
            snap_key = f"{SNAPSHOT_PREFIX}/{snapshot_id}/{relative_key}"
            live_key = (
                f"{manifest.source_prefix.rstrip('/')}/{relative_key}"
                if manifest.source_prefix
                else relative_key
            )
            copy = self._s3.copy_object(bucket, snap_key, bucket, live_key)
            if copy.succeeded and copy.checksum_sha256 == expected_checksum:
                report.restored_keys.append(live_key)
            else:
                report.failed_keys.append(live_key)

        return report

    def delete(self, bucket: str, snapshot_id: str) -> None:
        prefix = f"{SNAPSHOT_PREFIX}/{snapshot_id}/"
        for key in self._s3.list_objects(bucket, prefix=prefix):
            self._s3.delete_object(bucket, key)
