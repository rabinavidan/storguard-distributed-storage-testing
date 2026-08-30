"""Race condition runner — fires two competing operations with a small seeded
start-offset jitter so the same seed reproduces the same interleaving, then hands
back the observed operation order for outcome classification.

Race tests are only useful if a failure can be reproduced. Using ``random.Random(seed)``
for the jitter (instead of unmodified concurrency) means a failing seed can be re-run
in isolation to investigate exactly what interleaving triggered it.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Tuple


class RaceOutcome(str, Enum):
    ALLOWED = "allowed"        # a documented, acceptable end state
    FORBIDDEN = "forbidden"    # a correctness invariant was violated (e.g. torn/corrupt data)
    AMBIGUOUS = "ambiguous"    # outcome doesn't match any documented case — needs investigation


@dataclass
class RaceResult:
    scenario: str
    seed: int
    operation_order: List[str] = field(default_factory=list)
    outcome: RaceOutcome = RaceOutcome.AMBIGUOUS
    duration_ms: float = 0.0
    detail: str = ""

    def report(self) -> str:
        return (
            f"scenario={self.scenario} seed={self.seed} "
            f"order={'->'.join(self.operation_order)} "
            f"outcome={self.outcome.value} duration_ms={self.duration_ms:.1f}\n{self.detail}"
        )


def run_race(
    seed: int,
    op_a: Callable[[], None],
    op_b: Callable[[], None],
    jitter_ms: float = 5.0,
    label_a: str = "A",
    label_b: str = "B",
) -> Tuple[List[str], float]:
    """Run op_a and op_b concurrently with a seeded random start-offset jitter.

    Returns (observed_start_order, total_duration_ms). The order is derived from
    wall-clock timestamps taken immediately before each operation starts — it is
    best-effort, not a guarantee about which operation the server processed first.
    """
    rng = random.Random(seed)
    offset_a = rng.uniform(0, jitter_ms) / 1000.0
    offset_b = rng.uniform(0, jitter_ms) / 1000.0

    order: List[Tuple[float, str]] = []
    start = time.monotonic()

    def _wrapped(name: str, offset: float, fn: Callable[[], None]) -> None:
        if offset:
            time.sleep(offset)
        order.append((time.monotonic(), name))
        fn()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_wrapped, label_a, offset_a, op_a)
        f2 = pool.submit(_wrapped, label_b, offset_b, op_b)
        f1.result()
        f2.result()

    duration_ms = (time.monotonic() - start) * 1000
    order.sort(key=lambda t: t[0])
    return [name for _, name in order], duration_ms
