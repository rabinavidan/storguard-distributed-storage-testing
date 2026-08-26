"""StorGuard CLI — storguard <command> [options]"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()

COMPOSE_FILE = Path(__file__).parent.parent.parent / "infrastructure" / "docker-compose.yml"
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "infrastructure" / "scripts"


@click.group()
@click.version_option(version="0.1.0", prog_name="storguard")
def cli() -> None:
    """StorGuard — Reliability & Chaos Testing Platform for Distributed Storage Systems"""


# ─── storguard cluster ────────────────────────────────────────────────────────

@cli.group()
def cluster() -> None:
    """Manage the distributed MinIO storage cluster."""


@cluster.command("deploy")
@click.option("--profile", default="storage", help="Docker Compose profile to activate")
def cluster_deploy(profile: str) -> None:
    """Start the MinIO cluster and wait for health."""
    console.print(f"[bold cyan]Deploying cluster (profile={profile})...[/bold cyan]")
    _compose(["--profile", profile, "up", "-d"])
    _run_script("wait-for-health.sh")
    _write_allure_env()
    console.print("[bold green]Cluster ready.[/bold green]")
    console.print("  S3 API  : http://localhost:9000")
    console.print("  Console : http://localhost:9090")


@cluster.command("status")
def cluster_status() -> None:
    """Show container states and health."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "storage", "ps"],
        capture_output=True,
        text=True,
    )
    console.print(result.stdout)


@cluster.command("destroy")
@click.option("--volumes", is_flag=True, default=False, help="Also remove persistent volumes")
def cluster_destroy(volumes: bool) -> None:
    """Stop and remove the cluster."""
    args = ["--profile", "storage", "down"]
    if volumes:
        args.append("-v")
    _compose(args)
    console.print("[bold yellow]Cluster destroyed.[/bold yellow]")


# ─── storguard test ───────────────────────────────────────────────────────────

@cli.group()
def test() -> None:
    """Run a specific test suite."""


@test.command("smoke")
@click.option("--alluredir", default="allure-results")
def test_smoke(alluredir: str) -> None:
    """Run smoke tests (fast blocking health checks, <5 min)."""
    _pytest(["-m", "smoke", f"--alluredir={alluredir}", "-v"])


@test.command("functional")
@click.option("--workers", default=4, help="Parallel workers (pytest-xdist -n)")
@click.option("--alluredir", default="allure-results")
def test_functional(workers: int, alluredir: str) -> None:
    """Run functional + integrity tests."""
    _pytest(["-m", "functional or integrity", f"-n{workers}", f"--alluredir={alluredir}", "-v"])


@test.command("resilience")
@click.option("--alluredir", default="allure-results")
def test_resilience(alluredir: str) -> None:
    """Run resilience (chaos) tests."""
    _pytest(["-m", "resilience", f"--alluredir={alluredir}", "-v"])


@test.command("security")
@click.option("--alluredir", default="allure-results")
def test_security(alluredir: str) -> None:
    """Run security tests (auth, isolation, boundary inputs)."""
    _pytest(["-m", "security", f"--alluredir={alluredir}", "-v"])


# ─── storguard run ────────────────────────────────────────────────────────────

@cli.command("run")
@click.option("--scenario", required=True,
              type=click.Choice(["node-failure", "network-latency", "packet-loss", "disk-pressure"]))
@click.option("--workers", default=10, help="Concurrent S3 workers")
@click.option("--objects", default=50, help="Objects per workload run")
@click.option("--alluredir", default="allure-results")
def run_scenario(scenario: str, workers: int, objects: int, alluredir: str) -> None:
    """Run a single chaos scenario end-to-end."""
    console.print(f"[bold cyan]Running scenario: {scenario}[/bold cyan]")
    _pytest(["-m", "resilience", f"--alluredir={alluredir}", "-v", "-k", scenario.replace("-", "_")])


# ─── storguard baseline ───────────────────────────────────────────────────────

@cli.group()
def baseline() -> None:
    """Manage performance baselines."""


@baseline.command("capture")
@click.option("--output", default="baselines/latest.json")
def baseline_capture(output: str) -> None:
    """Run a workload and save metrics as the new baseline."""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    _pytest(["-m", "performance", f"--baseline-output={output}", "-v"])
    console.print(f"[green]Baseline saved to {output}[/green]")


@baseline.command("compare")
@click.option("--baseline", default="baselines/latest.json")
def baseline_compare(baseline: str) -> None:
    """Compare the last run against a saved baseline."""
    console.print(f"[cyan]Comparing against baseline: {baseline}[/cyan]")
    _pytest(["-m", "performance", f"--baseline={baseline}", "-v"])


# ─── storguard gate ───────────────────────────────────────────────────────────

@cli.group()
def gate() -> None:
    """Quality gate commands."""


@gate.command("evaluate")
@click.option("--config", default="config/local.yaml", help="Threshold config YAML")
@click.option("--metrics", default="baselines/latest.json", help="WorkloadMetrics JSON file")
def gate_evaluate(config: str, metrics: str) -> None:
    """Evaluate metrics against configured thresholds. Exits 1 on failure."""
    import yaml
    from storguard.models import WorkloadMetrics
    from storguard.quality_gate.gate import GateThresholds, QualityGate

    metrics_path = Path(metrics)
    if not metrics_path.exists():
        console.print(f"[red]Metrics file not found: {metrics}[/red]")
        console.print("Run [bold]storguard baseline capture[/bold] first.")
        sys.exit(1)

    config_path = Path(config)
    if not config_path.exists():
        console.print(f"[yellow]Config not found: {config} — using defaults[/yellow]")
        thresholds = GateThresholds()
    else:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        thresholds = GateThresholds.from_dict(raw.get("thresholds", {}))

    with open(metrics_path) as f:
        data = json.load(f)
    wm = WorkloadMetrics(**data)

    gate_obj = QualityGate(thresholds)
    result = gate_obj.evaluate(wm)

    table = Table(title="Quality Gate Evaluation", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_column("Threshold", style="white")
    table.add_column("Status", style="bold")

    table.add_row("Error rate", f"{wm.error_rate_percent}%",
                  f"<={thresholds.maximum_error_rate_percent}%",
                  "[green]OK[/green]" if wm.error_rate_percent <= thresholds.maximum_error_rate_percent else "[red]FAIL[/red]")
    table.add_row("P95 latency", f"{wm.latency_ms_p95}ms",
                  f"<={thresholds.maximum_p95_latency_ms}ms",
                  "[green]OK[/green]" if wm.latency_ms_p95 <= thresholds.maximum_p95_latency_ms else "[red]FAIL[/red]")
    table.add_row("Throughput", f"{wm.throughput_mbps} MB/s", "informational", "[cyan]—[/cyan]")

    console.print(table)

    if result.violations:
        console.print("\n[bold red]GATE FAILED[/bold red]")
        for v in result.violations:
            console.print(f"  [red]✗[/red] {v}")
        sys.exit(1)
    else:
        console.print("\n[bold green]GATE PASSED[/bold green]")


# ─── storguard monitor ────────────────────────────────────────────────────────

@cli.command("monitor")
@click.option("--refresh", default=3, type=int, help="Refresh interval in seconds")
def monitor(refresh: int) -> None:
    """Rich live terminal dashboard — cluster health, S3 probe, metrics, AI status."""
    from storguard.ai.ollama_client import OllamaClient
    from storguard.clients.docker_client import DockerClient
    from storguard.clients.s3_client import S3Client, S3Config
    from storguard.dashboard.monitor import ClusterMonitor

    s3     = S3Client(S3Config(endpoint="http://localhost:9000",
                               access_key="storguard",
                               secret_key="storguard_secret_123"))
    docker = DockerClient()
    ollama = OllamaClient()

    console.print("[cyan]Starting live monitor … press Ctrl+C to exit[/cyan]")
    try:
        ClusterMonitor(s3, docker, ollama, refresh_seconds=refresh).run()
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/dim]")
    finally:
        docker.close()


# ─── storguard demo ───────────────────────────────────────────────────────────

@cli.command("demo")
def demo_chaos() -> None:
    """Visual step-by-step chaos demo — node failure, recovery, AI analysis."""
    from storguard.ai.ollama_client import OllamaClient
    from storguard.clients.docker_client import DockerClient
    from storguard.clients.s3_client import S3Client, S3Config
    from storguard.dashboard.demo import run_demo

    s3     = S3Client(S3Config(endpoint="http://localhost:9000",
                               access_key="storguard",
                               secret_key="storguard_secret_123"))
    docker = DockerClient()
    ollama = OllamaClient()

    try:
        run_demo(s3, docker, ollama, console)
    finally:
        docker.close()


# ─── storguard ai ─────────────────────────────────────────────────────────────

@cli.group()
def ai() -> None:
    """AI-powered analysis and recommendations using local Ollama models."""


@ai.command("status")
@click.option("--host", default="http://localhost:11434", help="Ollama host URL")
def ai_status(host: str) -> None:
    """Check Ollama availability and list installed models."""
    from storguard.ai.ollama_client import OllamaClient, OllamaConfig

    client = OllamaClient(OllamaConfig(host=host))
    if not client.is_available():
        console.print(f"[red]Ollama not reachable at {host}[/red]")
        console.print("\nTo install and start:")
        console.print("  curl -fsSL https://ollama.com/install.sh | sh")
        console.print("  ollama pull llama3.2")
        console.print("  ollama serve")
        sys.exit(1)

    models = client.list_models()
    console.print(f"[green]Ollama reachable at {host}[/green]")

    table = Table(title="Installed Models")
    table.add_column("Model", style="cyan")
    for m in models:
        table.add_row(m)
    console.print(table)

    console.print("\nRecommended for StorGuard:")
    console.print("  ollama pull llama3.2       # 2 GB — best balance")
    console.print("  ollama pull llama3.2:1b    # 1.3 GB — fast on low RAM")
    console.print("  ollama pull mistral        # 4 GB — best JSON output")


@ai.command("analyze-logs")
@click.option("--container", default="storguard-minio1", help="Container name")
@click.option("--tail", default=200, type=int, help="Log lines to analyze")
@click.option("--model", default="llama3.2", help="Ollama model")
@click.option("--host", default="http://localhost:11434")
def ai_analyze_logs(container: str, tail: int, model: str, host: str) -> None:
    """Analyze container logs for anomalies using AI."""
    from storguard.ai.log_analyzer import LogAnalyzer
    from storguard.ai.ollama_client import OllamaClient, OllamaConfig
    from storguard.clients.docker_client import DockerClient

    docker = DockerClient()
    client = OllamaClient(OllamaConfig(host=host, model=model))

    with console.status(f"Fetching logs from [cyan]{container}[/cyan]..."):
        logs = docker.get_logs(container, tail=tail)

    with console.status(f"Analyzing with [cyan]{model}[/cyan]..."):
        analyzer = LogAnalyzer(client)
        result = analyzer.analyze(logs, container)

    severity_color = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}
    color = severity_color.get(result.severity, "white")

    console.print(f"\n[{color}]{result.format_report()}[/{color}]")
    if not result.ai_available:
        console.print("\n[yellow]Tip: run `storguard ai status` to check Ollama[/yellow]")


@ai.command("summarize")
@click.option("--metrics", default="baselines/latest.json", help="WorkloadMetrics JSON file")
@click.option("--model", default="llama3.2", help="Ollama model")
@click.option("--host", default="http://localhost:11434")
def ai_summarize(metrics: str, model: str, host: str) -> None:
    """Summarize test metrics in plain English using AI."""
    from storguard.ai.ollama_client import OllamaClient, OllamaConfig
    from storguard.ai.report_summarizer import ReportSummarizer
    from storguard.models import WorkloadMetrics

    path = Path(metrics)
    if not path.exists():
        console.print(f"[red]File not found: {metrics}[/red]")
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)
    wm = WorkloadMetrics(**data)

    client = OllamaClient(OllamaConfig(host=host, model=model))
    with console.status(f"Generating narrative with [cyan]{model}[/cyan]..."):
        summarizer = ReportSummarizer(client)
        narrative = summarizer.summarize_metrics(wm)

    console.print(f"\n{narrative.format_report()}")


@ai.command("advise")
@click.option("--metrics", default=None, help="WorkloadMetrics JSON file (optional)")
@click.option("--model", default="llama3.2", help="Ollama model")
@click.option("--host", default="http://localhost:11434")
def ai_advise(metrics: Optional[str], model: str, host: str) -> None:
    """Get AI-powered chaos scenario recommendations."""
    from storguard.ai.chaos_advisor import ChaosAdvisor
    from storguard.ai.ollama_client import OllamaClient, OllamaConfig
    from storguard.models import WorkloadMetrics

    wm = None
    if metrics:
        path = Path(metrics)
        if path.exists():
            with open(path) as f:
                wm = WorkloadMetrics(**json.load(f))

    client = OllamaClient(OllamaConfig(host=host, model=model))
    with console.status(f"Consulting [cyan]{model}[/cyan]..."):
        advisor = ChaosAdvisor(client)
        recs = advisor.recommend(metrics=wm)

    console.print("\n[bold]Chaos Scenario Recommendations[/bold]\n")
    for i, rec in enumerate(recs, 1):
        console.print(f"{i}. {rec.format()}\n")

    if not client.is_available():
        console.print("[yellow]Note: showing default recommendations (Ollama offline)[/yellow]")


# ─── storguard report ─────────────────────────────────────────────────────────

@cli.group()
def report() -> None:
    """Reporting commands."""


@report.command("generate")
@click.option("--results", default="allure-results")
@click.option("--output", default="allure-report")
def report_generate(results: str, output: str) -> None:
    """Generate an Allure HTML report from collected results."""
    try:
        subprocess.run(
            ["allure", "generate", results, "--output", output, "--clean"],
            check=True,
        )
        console.print(f"[green]Report generated: {output}/index.html[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Allure generation failed: {e}[/red]")
        sys.exit(1)
    except FileNotFoundError:
        console.print("[red]allure CLI not found — install from https://allurereport.org/docs/install/[/red]")
        sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _compose(args: List[str]) -> None:
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE)] + args,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Docker Compose failed (exit {e.returncode})[/red]")
        sys.exit(e.returncode)


def _run_script(name: str) -> None:
    try:
        subprocess.run(["bash", str(SCRIPTS_DIR / name)], check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Script {name} failed (exit {e.returncode})[/red]")
        sys.exit(e.returncode)


def _pytest(args: List[str]) -> None:
    try:
        subprocess.run([sys.executable, "-m", "pytest"] + args, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


def _write_allure_env() -> None:
    import platform
    results_dir = Path("allure-results")
    results_dir.mkdir(exist_ok=True)
    props = results_dir / "environment.properties"
    props.write_text(
        f"MINIO_VERSION=RELEASE.2024-07-04T14-25-45Z\n"
        f"CLUSTER_NODES=4\n"
        f"PYTHON_VERSION={platform.python_version()}\n"
        f"STORGUARD_VERSION=0.1.0\n"
        f"PLATFORM={platform.system()}\n"
    )


if __name__ == "__main__":
    cli()
