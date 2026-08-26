"""Chaos Controller — injects and safely removes infrastructure faults.

Every fault injection MUST be paired with restore() called in a finally block or
pytest fixture teardown. Diagnostic evidence is collected before cleanup.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator, List, Optional

from storguard.clients.docker_client import DockerClient
from storguard.models import FaultType, RecoveryTimeline


@dataclass
class FaultConfig:
    fault_type: FaultType
    target_container: str
    network_interface: str = "eth0"
    latency_ms: int = 200
    packet_loss_percent: int = 30
    disk_fill_path: str = "/data"
    disk_fill_mb: int = 10240   # 10 GB — adjust per environment


class ChaosController:
    def __init__(self, docker: DockerClient) -> None:
        self._docker = docker
        self._active_faults: List[FaultConfig] = []

    # ─── Node faults ──────────────────────────────────────────────────────────

    def stop_node(self, container_name: str) -> RecoveryTimeline:
        self._docker.stop_container(container_name)
        timeline = RecoveryTimeline(
            fault_injected_at=time.time(),
            fault_type=FaultType.NODE_STOP,
        )
        self._active_faults.append(
            FaultConfig(fault_type=FaultType.NODE_STOP, target_container=container_name)
        )
        return timeline

    def restart_node(self, container_name: str) -> None:
        self._docker.start_container(container_name)
        self._docker.wait_until_running(container_name, deadline_seconds=60)

    # ─── Network faults ───────────────────────────────────────────────────────

    def add_latency(
        self, container_name: str, latency_ms: int, interface: str = "eth0"
    ) -> RecoveryTimeline:
        cfg = FaultConfig(
            fault_type=FaultType.NETWORK_LATENCY,
            target_container=container_name,
            network_interface=interface,
            latency_ms=latency_ms,
        )
        self._docker.add_latency(container_name, interface, latency_ms)
        self._active_faults.append(cfg)
        return RecoveryTimeline(fault_injected_at=time.time(), fault_type=FaultType.NETWORK_LATENCY)

    def add_packet_loss(
        self, container_name: str, loss_percent: int, interface: str = "eth0"
    ) -> RecoveryTimeline:
        cfg = FaultConfig(
            fault_type=FaultType.PACKET_LOSS,
            target_container=container_name,
            network_interface=interface,
            packet_loss_percent=loss_percent,
        )
        self._docker.add_packet_loss(container_name, interface, loss_percent)
        self._active_faults.append(cfg)
        return RecoveryTimeline(fault_injected_at=time.time(), fault_type=FaultType.PACKET_LOSS)

    # ─── Disk pressure ────────────────────────────────────────────────────────

    def apply_disk_pressure(
        self, container_name: str, fill_mb: int, path: str = "/data"
    ) -> RecoveryTimeline:
        cfg = FaultConfig(
            fault_type=FaultType.DISK_PRESSURE,
            target_container=container_name,
            disk_fill_path=path,
            disk_fill_mb=fill_mb,
        )
        self._docker.fill_disk(container_name, path, fill_mb)
        self._active_faults.append(cfg)
        return RecoveryTimeline(fault_injected_at=time.time(), fault_type=FaultType.DISK_PRESSURE)

    # ─── Restore ──────────────────────────────────────────────────────────────

    def restore_all(self) -> None:
        """Remove all active faults. Call in finally / fixture teardown."""
        errors: List[str] = []
        for cfg in list(self._active_faults):
            try:
                self._restore_one(cfg)
            except Exception as exc:
                errors.append(f"{cfg.target_container}/{cfg.fault_type}: {exc}")
        self._active_faults.clear()
        if errors:
            raise RuntimeError(f"Restore errors: {errors}")

    def _restore_one(self, cfg: FaultConfig) -> None:
        if cfg.fault_type == FaultType.NODE_STOP:
            self._docker.start_container(cfg.target_container)
            self._docker.wait_until_running(cfg.target_container)
        elif cfg.fault_type in (FaultType.NETWORK_LATENCY, FaultType.PACKET_LOSS):
            self._docker.clear_tc_rules(cfg.target_container, cfg.network_interface)
        elif cfg.fault_type == FaultType.DISK_PRESSURE:
            self._docker.release_disk(cfg.target_container, cfg.disk_fill_path)

    # ─── Context manager (for single-fault tests) ─────────────────────────────

    @contextmanager
    def node_stopped(self, container_name: str) -> Generator[RecoveryTimeline, None, None]:
        timeline = self.stop_node(container_name)
        try:
            yield timeline
        finally:
            self.restart_node(container_name)
            timeline.fault_removed_at = time.time()
            self._active_faults = [
                f for f in self._active_faults
                if not (f.target_container == container_name and f.fault_type == FaultType.NODE_STOP)
            ]
