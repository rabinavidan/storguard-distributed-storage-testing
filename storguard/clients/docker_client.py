"""Low-level Docker client — docker-py wrapper for container orchestration and chaos injection."""

import time
from dataclasses import dataclass
from typing import List, Optional

import docker
from docker.models.containers import Container

from storguard.models import CommandResult


@dataclass
class ContainerState:
    name: str
    status: str
    running: bool
    health: Optional[str]


class DockerClient:
    def __init__(self) -> None:
        self._client = docker.from_env()

    # ─── Container lifecycle ──────────────────────────────────────────────────

    def stop_container(self, name: str, timeout: int = 10) -> None:
        container = self._get(name)
        container.stop(timeout=timeout)

    def start_container(self, name: str) -> None:
        container = self._get(name)
        container.start()

    def restart_container(self, name: str, timeout: int = 10) -> None:
        container = self._get(name)
        container.restart(timeout=timeout)

    def pause_container(self, name: str) -> None:
        self._get(name).pause()

    def unpause_container(self, name: str) -> None:
        self._get(name).unpause()

    # ─── Inspection ───────────────────────────────────────────────────────────

    def get_state(self, name: str) -> ContainerState:
        container = self._get(name)
        attrs = container.attrs
        health = (
            attrs.get("State", {})
            .get("Health", {})
            .get("Status")
        )
        return ContainerState(
            name=name,
            status=container.status,
            running=container.status == "running",
            health=health,
        )

    def get_logs(self, name: str, tail: int = 100) -> str:
        container = self._get(name)
        raw = container.logs(tail=tail, timestamps=True)
        return raw.decode(errors="replace")

    def get_all_states(self, name_prefix: str = "storguard") -> List[ContainerState]:
        containers = self._client.containers.list(
            all=True, filters={"name": name_prefix}
        )
        return [
            self.get_state(c.name) for c in containers  # type: ignore[attr-defined]
        ]

    # ─── In-container command execution (for fault injection) ─────────────────

    def exec_in_container(
        self,
        name: str,
        command: str,
        timeout_seconds: int = 30,
    ) -> CommandResult:
        container = self._get(name)
        start = time.monotonic()
        exit_code, output = container.exec_run(
            cmd=["sh", "-c", command],
            demux=False,
        )
        duration_ms = (time.monotonic() - start) * 1000
        stdout = output.decode(errors="replace") if output else ""
        return CommandResult(
            command=f"[{name}] {command}",
            stdout=stdout,
            stderr="",
            exit_code=exit_code or 0,
            duration_ms=duration_ms,
        )

    # ─── Network fault injection via tc inside container ─────────────────────

    def add_latency(self, container_name: str, interface: str, latency_ms: int) -> CommandResult:
        return self.exec_in_container(
            container_name,
            f"tc qdisc add dev {interface} root netem delay {latency_ms}ms",
        )

    def add_packet_loss(
        self, container_name: str, interface: str, loss_percent: int
    ) -> CommandResult:
        return self.exec_in_container(
            container_name,
            f"tc qdisc add dev {interface} root netem loss {loss_percent}%",
        )

    def clear_tc_rules(self, container_name: str, interface: str) -> CommandResult:
        return self.exec_in_container(
            container_name,
            f"tc qdisc del dev {interface} root 2>/dev/null || true",
        )

    # ─── Disk pressure via fallocate inside container ─────────────────────────

    def fill_disk(self, container_name: str, path: str, size_mb: int) -> CommandResult:
        return self.exec_in_container(
            container_name,
            f"fallocate -l {size_mb}M {path}/storguard_filler.bin",
        )

    def release_disk(self, container_name: str, path: str) -> CommandResult:
        return self.exec_in_container(
            container_name,
            f"rm -f {path}/storguard_filler.bin",
        )

    # ─── Health polling ───────────────────────────────────────────────────────

    def wait_until_running(
        self,
        name: str,
        deadline_seconds: int = 60,
        poll_interval: int = 2,
    ) -> bool:
        start = time.monotonic()
        while (time.monotonic() - start) < deadline_seconds:
            try:
                state = self.get_state(name)
                if state.running:
                    return True
            except Exception:
                pass
            time.sleep(poll_interval)
        return False

    def _get(self, name: str) -> Container:
        return self._client.containers.get(name)  # type: ignore[return-value]

    def close(self) -> None:
        self._client.close()
