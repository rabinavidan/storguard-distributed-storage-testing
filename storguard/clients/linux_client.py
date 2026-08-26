"""Low-level Linux client — subprocess wrapper that returns typed CommandResult objects."""

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from storguard.models import CommandResult


class LinuxCommandError(Exception):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(f"Command failed (exit={result.exit_code}): {result.command}")


class LinuxClient:
    def __init__(self, default_timeout_seconds: int = 30) -> None:
        self._default_timeout = default_timeout_seconds

    def execute(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
        raise_on_error: bool = False,
    ) -> CommandResult:
        timeout = timeout_seconds or self._default_timeout
        start = time.monotonic()
        timed_out = False
        stdout = stderr = ""
        exit_code = -1

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = (exc.stdout or b"").decode(errors="replace")
            stderr = (exc.stderr or b"").decode(errors="replace")

        result = CommandResult(
            command=command,
            stdout=stdout.strip(),
            stderr=stderr.strip(),
            exit_code=exit_code,
            duration_ms=(time.monotonic() - start) * 1000,
            timed_out=timed_out,
        )

        if raise_on_error and not result.succeeded:
            raise LinuxCommandError(result)

        return result

    # ─── System diagnostics ───────────────────────────────────────────────────

    def get_cpu_info(self) -> CommandResult:
        return self.execute("top -bn1 | grep 'Cpu(s)'")

    def get_memory_info(self) -> CommandResult:
        return self.execute("free -h")

    def get_disk_info(self) -> CommandResult:
        return self.execute("df -h")

    def get_mounts(self) -> CommandResult:
        return self.execute("mount | grep -v 'tmpfs\\|devtmpfs'")

    def get_open_ports(self) -> CommandResult:
        return self.execute("ss -tlnp")

    def get_processes(self, name_filter: str = "") -> CommandResult:
        cmd = f"ps aux | grep '{name_filter}'" if name_filter else "ps aux"
        return self.execute(cmd)

    def check_service_health(self, service_name: str) -> CommandResult:
        return self.execute(f"systemctl is-active {service_name} 2>/dev/null || echo inactive")

    def filter_logs(self, log_path: str, pattern: str, tail_lines: int = 100) -> CommandResult:
        return self.execute(f"tail -n {tail_lines} {log_path} | grep '{pattern}'")

    # ─── Network diagnostics ──────────────────────────────────────────────────

    def check_dns(self, hostname: str) -> CommandResult:
        return self.execute(f"dig +short {hostname} || getent hosts {hostname}")

    def ping(self, host: str, count: int = 3) -> CommandResult:
        return self.execute(f"ping -c {count} -W 2 {host}")

    def check_tcp_port(self, host: str, port: int, timeout_seconds: int = 5) -> CommandResult:
        return self.execute(f"nc -zv -w {timeout_seconds} {host} {port} 2>&1")

    def check_route(self, host: str) -> CommandResult:
        return self.execute(f"traceroute -m 5 -w 1 {host} 2>&1 | head -10")

    # ─── Fault injection via tc (traffic control) ─────────────────────────────

    def add_network_latency(self, interface: str, latency_ms: int) -> CommandResult:
        return self.execute(
            f"tc qdisc add dev {interface} root netem delay {latency_ms}ms",
            raise_on_error=True,
        )

    def add_packet_loss(self, interface: str, loss_percent: int) -> CommandResult:
        return self.execute(
            f"tc qdisc add dev {interface} root netem loss {loss_percent}%",
            raise_on_error=True,
        )

    def clear_tc_rules(self, interface: str) -> CommandResult:
        return self.execute(f"tc qdisc del dev {interface} root 2>/dev/null || true")
