"""Rich live terminal dashboard — real-time cluster health, S3 probe, metrics, AI status."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from storguard.ai.ollama_client import OllamaClient
from storguard.clients.docker_client import DockerClient
from storguard.clients.s3_client import S3Client

_NODES = [
    "storguard-minio1",
    "storguard-minio2",
    "storguard-minio3",
    "storguard-minio4",
    "storguard-gateway",
]
_MAX_LOG = 10
_ProbeEntry = Tuple[str, str, str, str]   # time · op · key · result


class ClusterMonitor:
    def __init__(
        self,
        s3: S3Client,
        docker: DockerClient,
        ollama: OllamaClient,
        refresh_seconds: int = 3,
    ) -> None:
        self._s3 = s3
        self._docker = docker
        self._ollama = ollama
        self._refresh = refresh_seconds
        self._log: List[_ProbeEntry] = []
        self._bucket = f"storguard-mon-{uuid.uuid4().hex[:6]}"
        self._probe_n = 0
        self._last_put_ms: Optional[float] = None
        self._errors = 0

    # ─── Public ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._s3.create_bucket(self._bucket)
        except Exception:
            pass

        try:
            with Live(
                self._build(),
                refresh_per_second=1,
                screen=True,
                vertical_overflow="visible",
            ) as live:
                while True:
                    self._probe()
                    live.update(self._build())
                    time.sleep(self._refresh)
        finally:
            self._cleanup()

    # ─── Layout ───────────────────────────────────────────────────────────────

    def _build(self) -> Layout:
        root = Layout()
        root.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=4),
        )
        root["body"].split_row(
            Layout(name="health", ratio=2),
            Layout(name="probe",  ratio=3),
            Layout(name="stats",  ratio=2),
        )
        root["header"].update(self._header())
        root["health"].update(self._health_panel())
        root["probe"].update(self._probe_panel())
        root["stats"].update(self._stats_panel())
        root["footer"].update(self._footer())
        return root

    # ─── Panels ───────────────────────────────────────────────────────────────

    def _header(self) -> Panel:
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        return Panel(
            Text(
                f"StorGuard  —  Live Cluster Monitor  ·  {ts}  ·  refresh {self._refresh}s",
                justify="center",
                style="bold cyan",
            ),
            style="cyan",
        )

    def _health_panel(self) -> Panel:
        t = Table.grid(padding=(0, 1))
        t.add_column(width=2)
        t.add_column(width=18)
        t.add_column(width=9)
        t.add_column(width=9)

        for name in _NODES:
            short = name.replace("storguard-", "")
            try:
                st = self._docker.get_state(name)
                dot    = "[bold green]●[/bold green]" if st.running else "[bold red]●[/bold red]"
                status = f"[green]{st.status}[/green]" if st.running else f"[red]{st.status}[/red]"
                health = f"[green]{st.health}[/green]" if st.health else "[dim]—[/dim]"
            except Exception:
                dot, status, health = "[dim]○[/dim]", "[dim]unknown[/dim]", "[dim]—[/dim]"
            t.add_row(dot, short, status, health)

        return Panel(t, title="[bold]Cluster Nodes[/bold]", border_style="green")

    def _probe_panel(self) -> Panel:
        t = Table.grid(padding=(0, 1))
        t.add_column(width=9)
        t.add_column(width=4)
        t.add_column(width=28)
        t.add_column()

        rows = self._log[-_MAX_LOG:]
        for ts, op, key, result in rows:
            colour = {"PUT": "cyan", "GET": "blue", "DEL": "yellow"}.get(op, "white")
            t.add_row(
                f"[dim]{ts}[/dim]",
                f"[{colour}]{op}[/{colour}]",
                f"[dim]{key}[/dim]",
                result,
            )

        if not rows:
            t.add_row("", "", "[dim italic]waiting for first probe …[/dim italic]", "")

        subtitle = f"[dim]probe #{self._probe_n}  ·  {self._errors} errors[/dim]"
        return Panel(t, title="[bold]Live S3 Probe[/bold]", subtitle=subtitle, border_style="blue")

    def _stats_panel(self) -> Panel:
        g = Table.grid(padding=(0, 1))
        g.add_column(style="dim", width=14)
        g.add_column()

        # Baseline metrics from disk
        path = Path("baselines/latest.json")
        if path.exists():
            try:
                data = json.loads(path.read_text())
                g.add_row("Throughput",  f"[bold cyan]{data.get('throughput_mbps', '—')} MB/s[/bold cyan]")
                g.add_row("Error rate",  f"[green]{data.get('error_rate_percent', '—')}%[/green]")
                g.add_row("Avg latency", f"{data.get('latency_ms_avg', '—')} ms")
                g.add_row("P95 latency", f"{data.get('latency_ms_p95', '—')} ms")
                g.add_row("P99 latency", f"{data.get('latency_ms_p99', '—')} ms")
                g.add_row("Total ops",   str(data.get('total_operations', '—')))
                g.add_row("", "")
                g.add_row("[dim]source[/dim]", "[dim]baselines/latest.json[/dim]")
            except Exception:
                g.add_row("", "[dim]error reading metrics[/dim]")
        else:
            g.add_row("", "[dim italic]run:[/dim italic]")
            g.add_row("", "[dim]storguard baseline capture[/dim]")

        # Live probe latency
        if self._last_put_ms is not None:
            g.add_row("", "")
            g.add_row("Last PUT",  f"[cyan]{self._last_put_ms:.0f} ms[/cyan]")
            g.add_row("Probe #",   str(self._probe_n))

        return Panel(g, title="[bold]Last Workload[/bold]", border_style="magenta")

    def _footer(self) -> Panel:
        ai_dot   = "[green]●[/green]" if self._ollama.is_available() else "[red]●[/red]"
        ai_label = "online" if self._ollama.is_available() else "offline"
        t = Table.grid(padding=(0, 2))
        t.add_column()
        t.add_column()
        t.add_column()
        t.add_row(
            f"  Ollama {ai_dot} [dim]{ai_label}  gemma4:26b[/dim]",
            "[dim]Ctrl+C to exit[/dim]",
            "[cyan]storguard ai analyze-logs[/cyan] [dim]for AI log analysis[/dim]",
        )
        t.add_row(
            "  [dim]MinIO Console: http://localhost:9090[/dim]",
            "[dim]Grafana: http://localhost:3000[/dim]",
            "[dim]Allure: http://localhost:5252[/dim]",
        )
        return Panel(t, style="dim")

    # ─── Probe ────────────────────────────────────────────────────────────────

    def _probe(self) -> None:
        self._probe_n += 1
        key = f"probe/chk-{self._probe_n:05d}"
        now = datetime.now().strftime("%H:%M:%S")

        put = self._s3.upload_object(self._bucket, key, b"storguard-health-probe")
        if put.succeeded:
            self._last_put_ms = put.duration_ms
            self._add(now, "PUT", key, f"[green]OK[/green]  {put.duration_ms:.0f}ms")

            get = self._s3.download_object(self._bucket, key)
            self._add(now, "GET", key,
                      f"[green]OK[/green]  {get.duration_ms:.0f}ms" if get.succeeded
                      else f"[red]ERR[/red] {get.error_code}")

            rm = self._s3.delete_object(self._bucket, key)
            self._add(now, "DEL", key,
                      f"[green]OK[/green]  {rm.duration_ms:.0f}ms" if rm.succeeded
                      else f"[red]ERR[/red] {rm.error_code}")
        else:
            self._errors += 1
            self._add(now, "PUT", key, f"[red]FAIL[/red] {put.error_code or put.error}")

    def _add(self, ts: str, op: str, key: str, result: str) -> None:
        self._log.append((ts, op, f"…{key[-26:]}", result))

    def _cleanup(self) -> None:
        try:
            for k in self._s3.list_objects(self._bucket):
                self._s3.delete_object(self._bucket, k)
            self._s3.delete_bucket(self._bucket)
        except Exception:
            pass
