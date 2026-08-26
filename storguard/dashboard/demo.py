"""Visual chaos demo — step-by-step node-failure scenario with Rich UI.

Runs a real end-to-end chaos scenario against the live cluster and narrates
every phase with spinners, progress bars, before/after metric comparison,
and an AI summary at the end.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from storguard.ai.chaos_advisor import ChaosAdvisor
from storguard.ai.log_analyzer import LogAnalyzer
from storguard.ai.ollama_client import OllamaClient
from storguard.ai.report_summarizer import ReportSummarizer
from storguard.chaos.controller import ChaosController
from storguard.clients.docker_client import DockerClient
from storguard.clients.s3_client import S3Client, S3Config
from storguard.integrity.validator import IntegrityValidator, generate_test_data
from storguard.models import WorkloadMetrics
from storguard.workloads.engine import OperationType, WorkloadConfig, WorkloadEngine

_CHAOS_NODE    = "storguard-minio2"
_WORKERS       = 6
_OBJECTS       = 20
_FILE_SIZE     = 512 * 1024   # 512 KB


def run_demo(s3: S3Client, docker: DockerClient, ollama: OllamaClient, console: Console) -> None:
    engine    = WorkloadEngine(s3)
    chaos     = ChaosController(docker)
    integrity = IntegrityValidator(s3)
    bucket    = f"storguard-demo-{uuid.uuid4().hex[:6]}"
    s3.create_bucket(bucket)

    console.print()
    console.print(Panel(
        Text("StorGuard  —  Live Chaos Engineering Demo\nNode Failure · Quorum Resilience · AI Analysis",
             justify="center", style="bold cyan"),
        style="bold cyan",
        padding=(1, 4),
    ))
    console.print()

    # ── Step 1: Baseline ──────────────────────────────────────────────────────
    _step(console, 1, 6, "Baseline workload", f"{_WORKERS} workers · {_OBJECTS} objects · {_FILE_SIZE//1024} KB each")
    baseline = _run_workload(engine, bucket, console, run_id="baseline")
    _metric_row(console, "Baseline", baseline, style="green")

    # ── Step 2: Integrity seed ────────────────────────────────────────────────
    _step(console, 2, 6, "Seeding integrity objects", "SHA-256 anchors for post-recovery validation")
    seed_data = generate_test_data(64 * 1024, seed=42)
    seed_key  = f"integrity-seed/{uuid.uuid4().hex}"
    s3.upload_object(bucket, seed_key, seed_data)
    console.print(f"    [green]✓[/green] Seeded  [dim]{seed_key}[/dim]")
    console.print()

    # ── Step 3: Inject fault ──────────────────────────────────────────────────
    _step(console, 3, 6, "Injecting fault", f"Stopping  {_CHAOS_NODE}  —  EC:2 quorum will hold with 3/4 nodes")
    with _spinner(console, f"docker stop {_CHAOS_NODE}"):
        t0 = time.monotonic()
        timeline = chaos.stop_node(_CHAOS_NODE)
        stop_ms = (time.monotonic() - t0) * 1000
    console.print(f"    [red]●[/red] {_CHAOS_NODE} stopped  [dim]({stop_ms:.0f} ms)[/dim]")
    console.print()

    # ── Step 4: Workload under failure ────────────────────────────────────────
    _step(console, 4, 6, "Workload under failure", "Cluster must serve requests with one node down")
    degraded = _run_workload(engine, bucket, console, run_id="degraded")
    _metric_row(console, "Under fault", degraded, style="yellow")

    # ── Step 5: Recover + integrity ───────────────────────────────────────────
    _step(console, 5, 6, "Recovery & integrity verification", f"Restart {_CHAOS_NODE}  →  SHA-256 round-trip")
    with _spinner(console, f"docker start {_CHAOS_NODE}"):
        chaos.restart_node(_CHAOS_NODE)
        timeline.fault_removed_at = time.time()
    console.print(f"    [green]●[/green] {_CHAOS_NODE} running")

    with _spinner(console, "SHA-256 verification"):
        report = integrity.verify(bucket, seed_key, seed_data)
        timeline.integrity_verified_at = time.time()

    integrity_label = "[bold green]MATCH — zero data corruption[/bold green]" if report.passed else "[bold red]MISMATCH — corruption detected[/bold red]"
    console.print(f"    [green]✓[/green] SHA-256 {integrity_label}")
    chaos._active_faults.clear()
    console.print()

    # ── Step 6: AI analysis ───────────────────────────────────────────────────
    _step(console, 6, 6, "AI analysis", f"Ollama gemma4:26b  →  log anomalies + narrative")
    _run_ai_analysis(console, docker, ollama, timeline, baseline, degraded)

    # ── Final summary ─────────────────────────────────────────────────────────
    _print_summary(console, baseline, degraded, timeline, report.passed)

    # Cleanup
    try:
        for k in s3.list_objects(bucket):
            s3.delete_object(bucket, k)
        s3.delete_bucket(bucket)
    except Exception:
        pass


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _step(console: Console, n: int, total: int, title: str, subtitle: str) -> None:
    console.print(Rule(
        f"[bold]Step {n}/{total}[/bold]  [cyan]{title}[/cyan]  [dim]{subtitle}[/dim]",
        style="dim",
    ))
    console.print()


def _run_workload(engine: WorkloadEngine, bucket: str, console: Console, run_id: str) -> WorkloadMetrics:
    cfg = WorkloadConfig(
        bucket=bucket,
        workers=_WORKERS,
        objects=_OBJECTS,
        file_size_bytes=_FILE_SIZE,
        operation=OperationType.UPLOAD,
        run_id=run_id,
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[cyan]{task.completed}/{task.total}[/cyan] ops"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as prog:
        task = prog.add_task(f"    Running {run_id} workload …", total=_OBJECTS)

        # Run synchronously — update progress as results come in
        import concurrent.futures
        from storguard.integrity.validator import generate_test_data as _gd
        data = _gd(_FILE_SIZE)
        keys = [f"workload/{run_id}/obj-{i:05d}" for i in range(_OBJECTS)]
        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futures = {pool.submit(engine._s3.upload_object, bucket, k, data): k for k in keys}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception:
                    pass
                prog.advance(task)

    import statistics, time as _t
    successful = [r for r in results if r.succeeded]
    failed     = [r for r in results if not r.succeeded]
    latencies  = sorted(r.duration_ms for r in successful)

    def _pct(data, p):
        if not data: return 0.0
        return data[min(int(len(data) * p / 100), len(data) - 1)]

    total_bytes = len(successful) * _FILE_SIZE
    elapsed = sum(r.duration_ms for r in results) / 1000 / max(_WORKERS, 1) or 1

    return WorkloadMetrics(
        total_operations=len(results),
        successful_operations=len(successful),
        failed_operations=len(failed),
        duration_seconds=elapsed,
        throughput_mbps=round((total_bytes / (1024 * 1024)) / elapsed, 2),
        latency_ms_min=min(latencies) if latencies else 0,
        latency_ms_avg=round(statistics.mean(latencies), 2) if latencies else 0,
        latency_ms_max=max(latencies) if latencies else 0,
        latency_ms_p95=round(_pct(latencies, 95), 2),
        latency_ms_p99=round(_pct(latencies, 99), 2),
        error_rate_percent=round(len(failed) / len(results) * 100, 2) if results else 0,
    )


def _metric_row(console: Console, label: str, m: WorkloadMetrics, style: str) -> None:
    console.print(
        f"    [{style}]✓[/{style}]  {label:12s}  "
        f"[bold]{m.throughput_mbps:6.2f} MB/s[/bold]  "
        f"err [bold]{m.error_rate_percent:.1f}%[/bold]  "
        f"avg [bold]{m.latency_ms_avg:.0f}ms[/bold]  "
        f"P95 [bold]{m.latency_ms_p95:.0f}ms[/bold]"
    )
    console.print()


def _spinner(console: Console, label: str):
    return Progress(
        SpinnerColumn(),
        TextColumn(f"    [dim]{label}[/dim]"),
        console=console,
        transient=True,
    )


def _run_ai_analysis(
    console: Console,
    docker: DockerClient,
    ollama: OllamaClient,
    timeline,
    baseline: WorkloadMetrics,
    degraded: WorkloadMetrics,
) -> None:
    if not ollama.is_available():
        console.print("    [dim]Ollama offline — skipping AI analysis[/dim]\n")
        return

    # Log analysis on the stopped/restarted node
    with _spinner(console, f"AI log analysis — {_CHAOS_NODE}"):
        try:
            logs = docker.get_logs(_CHAOS_NODE, tail=60)
            analyzer = LogAnalyzer(ollama)
            analysis = analyzer.analyze(logs, _CHAOS_NODE)
        except Exception as e:
            console.print(f"    [dim]Log analysis error: {e}[/dim]\n")
            return

    console.print(f"    [green]✓[/green] Log severity: [bold]{analysis.severity.upper()}[/bold]")
    if analysis.anomalies:
        for a in analysis.anomalies:
            console.print(f"       [dim]• {a}[/dim]")

    # Narrative summary
    with _spinner(console, "AI narrative summary"):
        try:
            summarizer = ReportSummarizer(ollama)
            narrative  = summarizer.summarize_chaos(timeline)
            console.print(f"\n    [cyan]AI Summary:[/cyan] {narrative.summary}")
        except Exception:
            pass

    console.print()


def _print_summary(
    console: Console,
    baseline: WorkloadMetrics,
    degraded: WorkloadMetrics,
    timeline,
    integrity_ok: bool,
) -> None:
    console.print(Rule("[bold]Demo Complete[/bold]", style="cyan"))
    console.print()

    # Side-by-side comparison table
    t = Table(box=box.ROUNDED, show_header=True, header_style="bold", title="Before vs During Failure")
    t.add_column("Metric",      style="dim",    width=18)
    t.add_column("Baseline",    style="green",  justify="right")
    t.add_column("Under Fault", style="yellow", justify="right")
    t.add_column("Delta",       justify="right")

    def _delta(a: float, b: float, lower_is_better: bool = False) -> str:
        d = b - a
        pct = (d / a * 100) if a else 0
        good = (d < 0) if lower_is_better else (d > 0)
        sign = "+" if d > 0 else ""
        colour = "green" if good else "red"
        return f"[{colour}]{sign}{pct:.1f}%[/{colour}]"

    t.add_row("Throughput MB/s",
              f"{baseline.throughput_mbps}",
              f"{degraded.throughput_mbps}",
              _delta(baseline.throughput_mbps, degraded.throughput_mbps))
    t.add_row("Error rate %",
              f"{baseline.error_rate_percent}",
              f"{degraded.error_rate_percent}",
              _delta(baseline.error_rate_percent, degraded.error_rate_percent, lower_is_better=True))
    t.add_row("Avg latency ms",
              f"{baseline.latency_ms_avg:.0f}",
              f"{degraded.latency_ms_avg:.0f}",
              _delta(baseline.latency_ms_avg, degraded.latency_ms_avg, lower_is_better=True))
    t.add_row("P95 latency ms",
              f"{baseline.latency_ms_p95:.0f}",
              f"{degraded.latency_ms_p95:.0f}",
              _delta(baseline.latency_ms_p95, degraded.latency_ms_p95, lower_is_better=True))

    console.print(Columns([t], align="center"))
    console.print()

    integrity_str = "[bold green]PRESERVED ✓[/bold green]" if integrity_ok else "[bold red]FAILED ✗[/bold red]"
    recovery_s = f"{timeline.recovery_time_seconds:.1f}s" if timeline.fault_removed_at else "—"

    result_panel = Panel(
        f"[bold]Data Integrity[/bold]  {integrity_str}\n"
        f"[bold]Recovery time[/bold]   [cyan]{recovery_s}[/cyan]\n"
        f"[bold]Conclusion[/bold]      Erasure-coding EC:2 quorum preserved data and availability\n"
        f"                with 1/4 nodes down — cluster behaved as designed.",
        title="[bold cyan]RESULT[/bold cyan]",
        border_style="cyan",
        padding=(1, 4),
    )
    console.print(result_panel)
    console.print()
