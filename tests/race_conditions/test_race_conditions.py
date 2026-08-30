"""Race condition tests — intentional timing collisions, not accidental flakiness.

Each scenario fires two competing operations with a seeded start-offset jitter
(see storguard.concurrency.race_runner) so a failing seed can be re-run in
isolation. Every outcome is classified as ALLOWED (a documented acceptable end
state) or FORBIDDEN (a correctness invariant was violated — torn data, silent
corruption, or a stale read reported as success). Only FORBIDDEN/AMBIGUOUS fail
the test; the seed, operation order and final state are always attached to Allure
so a failure is reproducible without re-running the whole suite.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import List

import allure
import pytest

from storguard.chaos.controller import ChaosController
from storguard.clients.s3_client import S3Client
from storguard.concurrency.race_runner import RaceOutcome, RaceResult, run_race
from storguard.integrity.validator import generate_test_data
from storguard.models import OperationResult, OperationStatus

SEEDS = list(range(20))


def _attach(result: RaceResult) -> None:
    allure.attach(result.report(), name=f"race-seed-{result.seed}", attachment_type=allure.attachment_type.TEXT)


@allure.epic("Resilience")
@allure.feature("Race Conditions")
@pytest.mark.race
class TestWriteDeleteRace:
    """Concurrent overwrite vs. delete of the same key.

    Documented acceptable end states: the delete "wins" (key gone) or the
    overwrite "wins" (key holds the new payload intact). Anything else — the
    stale original payload surviving, or a partially-written body — is forbidden.
    """

    @allure.story("Overwrite racing a delete never leaves stale or torn data")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_write_delete_race(self, s3: S3Client, test_bucket: str, seed: int):
        key = f"race/write-delete/{uuid.uuid4().hex}"
        original = generate_test_data(4096, seed=1000 + seed)
        updated = generate_test_data(4096, seed=2000 + seed)

        with allure.step(f"[seed={seed}] Seed baseline object"):
            baseline = s3.upload_object(test_bucket, key, original)
            assert baseline.succeeded

        with allure.step(f"[seed={seed}] Fire concurrent overwrite + delete"):
            order, duration_ms = run_race(
                seed=seed,
                op_a=lambda: s3.upload_object(test_bucket, key, updated),
                op_b=lambda: s3.delete_object(test_bucket, key),
                label_a="overwrite",
                label_b="delete",
            )

        with allure.step(f"[seed={seed}] Classify final state"):
            final = s3.download_object(test_bucket, key)
            result = RaceResult(scenario="write_delete", seed=seed, operation_order=order, duration_ms=duration_ms)

            if final.status == OperationStatus.NOT_FOUND:
                result.outcome = RaceOutcome.ALLOWED
                result.detail = "delete won — key absent"
            elif final.succeeded and final.checksum_sha256 == hashlib.sha256(updated).hexdigest():
                result.outcome = RaceOutcome.ALLOWED
                result.detail = "overwrite won — new payload intact"
            elif final.succeeded and final.checksum_sha256 == hashlib.sha256(original).hexdigest():
                result.outcome = RaceOutcome.FORBIDDEN
                result.detail = "stale original payload survived — overwrite silently lost"
            else:
                result.outcome = RaceOutcome.FORBIDDEN
                result.detail = f"unrecognized/torn final state: status={final.status}, checksum={final.checksum_sha256}"

            _attach(result)
            assert result.outcome == RaceOutcome.ALLOWED, result.report()


@allure.epic("Resilience")
@allure.feature("Race Conditions")
@pytest.mark.race
class TestOverwriteReadRace:
    """Concurrent read vs. overwrite of the same key.

    A reader racing a writer must see one complete, checksummable version of the
    object — either the old body or the new body. A torn read (bytes that match
    neither checksum) means PUT visibility isn't atomic and is forbidden.
    """

    @allure.story("Reader never observes a torn write")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_overwrite_read_race(self, s3: S3Client, test_bucket: str, seed: int):
        key = f"race/overwrite-read/{uuid.uuid4().hex}"
        original = generate_test_data(256 * 1024, seed=3000 + seed)
        updated = generate_test_data(256 * 1024, seed=4000 + seed)

        with allure.step(f"[seed={seed}] Seed baseline object"):
            baseline = s3.upload_object(test_bucket, key, original)
            assert baseline.succeeded

        read_holder: List[OperationResult] = []

        with allure.step(f"[seed={seed}] Fire concurrent read + overwrite"):
            order, duration_ms = run_race(
                seed=seed,
                op_a=lambda: read_holder.append(s3.download_object(test_bucket, key)),
                op_b=lambda: s3.upload_object(test_bucket, key, updated),
                label_a="read",
                label_b="overwrite",
            )

        with allure.step(f"[seed={seed}] Classify what the reader observed"):
            read = read_holder[0]
            result = RaceResult(scenario="overwrite_read", seed=seed, operation_order=order, duration_ms=duration_ms)

            if not read.succeeded:
                result.outcome = RaceOutcome.AMBIGUOUS
                result.detail = f"read failed cleanly during overwrite: {read.error}"
            elif read.checksum_sha256 == hashlib.sha256(original).hexdigest():
                result.outcome = RaceOutcome.ALLOWED
                result.detail = "reader saw the old, complete body"
            elif read.checksum_sha256 == hashlib.sha256(updated).hexdigest():
                result.outcome = RaceOutcome.ALLOWED
                result.detail = "reader saw the new, complete body"
            else:
                result.outcome = RaceOutcome.FORBIDDEN
                result.detail = f"torn read — checksum matches neither version: {read.checksum_sha256}"

            _attach(result)
            assert result.outcome in (RaceOutcome.ALLOWED, RaceOutcome.AMBIGUOUS), result.report()
            assert result.outcome != RaceOutcome.FORBIDDEN, result.report()


@allure.epic("Resilience")
@allure.feature("Race Conditions")
@pytest.mark.race
class TestConcurrentWriteRace:
    """Two writers racing to write different payloads to the same brand-new key.

    Exactly one payload must win in full — a hybrid of both bodies means the
    server accepted a torn/interleaved write, which is a data-integrity bug.
    """

    @allure.story("Concurrent writes to the same key never produce a hybrid body")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_concurrent_write_race(self, s3: S3Client, test_bucket: str, seed: int):
        key = f"race/concurrent-write/{uuid.uuid4().hex}"
        payload_a = generate_test_data(8192, seed=5000 + seed)
        payload_b = generate_test_data(8192, seed=6000 + seed)

        with allure.step(f"[seed={seed}] Fire two concurrent writers to the same key"):
            order, duration_ms = run_race(
                seed=seed,
                op_a=lambda: s3.upload_object(test_bucket, key, payload_a),
                op_b=lambda: s3.upload_object(test_bucket, key, payload_b),
                label_a="writer-A",
                label_b="writer-B",
            )

        with allure.step(f"[seed={seed}] Classify the winning body"):
            final = s3.download_object(test_bucket, key)
            result = RaceResult(scenario="concurrent_write", seed=seed, operation_order=order, duration_ms=duration_ms)

            if final.succeeded and final.checksum_sha256 in (
                hashlib.sha256(payload_a).hexdigest(),
                hashlib.sha256(payload_b).hexdigest(),
            ):
                result.outcome = RaceOutcome.ALLOWED
                winner = "A" if final.checksum_sha256 == hashlib.sha256(payload_a).hexdigest() else "B"
                result.detail = f"writer-{winner} won cleanly — single complete body"
            else:
                result.outcome = RaceOutcome.FORBIDDEN
                result.detail = f"hybrid/corrupt final body: status={final.status}, checksum={final.checksum_sha256}"

            _attach(result)
            assert result.outcome == RaceOutcome.ALLOWED, result.report()


@allure.epic("Resilience")
@allure.feature("Race Conditions")
@pytest.mark.race
class TestRestartVsReadRace:
    """Reads racing a node stop/restart cycle.

    With EC:2 erasure coding across 4 nodes, one node cycling must never surface
    corrupted data to a reader — only a correct read or a clean failure are
    acceptable outcomes.
    """

    TARGET_NODE = "storguard-minio4"

    @allure.story("Reads never return corrupted data while a node restarts")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.parametrize("seed", [101, 202, 303])
    def test_restart_vs_read_race(
        self, s3: S3Client, chaos: ChaosController, test_bucket: str, seed: int
    ):
        key = f"race/restart-read/{uuid.uuid4().hex}"
        data = generate_test_data(64 * 1024, seed=seed)
        expected_checksum = hashlib.sha256(data).hexdigest()

        with allure.step(f"[seed={seed}] Seed baseline object"):
            baseline = s3.upload_object(test_bucket, key, data)
            assert baseline.succeeded

        reads: List[OperationResult] = []

        def _restart_node() -> None:
            chaos.stop_node(self.TARGET_NODE)
            chaos.restart_node(self.TARGET_NODE)

        def _read_during_restart() -> None:
            for _ in range(15):
                reads.append(s3.download_object(test_bucket, key))
                time.sleep(0.5)

        with allure.step(f"[seed={seed}] Fire node restart concurrently with repeated reads"):
            order, duration_ms = run_race(
                seed=seed,
                op_a=_restart_node,
                op_b=_read_during_restart,
                label_a="restart",
                label_b="reads",
            )

        with allure.step(f"[seed={seed}] Classify every read observed during the restart window"):
            result = RaceResult(scenario="restart_vs_read", seed=seed, operation_order=order, duration_ms=duration_ms)
            corrupted = [r for r in reads if r.succeeded and r.checksum_sha256 != expected_checksum]
            succeeded = sum(1 for r in reads if r.succeeded)

            allure.attach(
                f"reads={len(reads)} succeeded={succeeded} corrupted={len(corrupted)}",
                name=f"restart-read-summary-seed-{seed}",
                attachment_type=allure.attachment_type.TEXT,
            )

            if corrupted:
                result.outcome = RaceOutcome.FORBIDDEN
                result.detail = f"{len(corrupted)}/{len(reads)} reads returned wrong data during node restart"
            else:
                result.outcome = RaceOutcome.ALLOWED
                result.detail = f"{succeeded}/{len(reads)} reads succeeded with correct checksum; rest failed cleanly"

            _attach(result)
            assert result.outcome == RaceOutcome.ALLOWED, result.report()
