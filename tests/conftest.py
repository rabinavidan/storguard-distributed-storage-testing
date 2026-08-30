"""Root conftest — fixtures shared across all test suites."""

from __future__ import annotations

import os
import uuid
from typing import Generator

import allure
import pytest

from storguard.clients.docker_client import DockerClient
from storguard.clients.linux_client import LinuxClient
from storguard.clients.s3_client import S3Client, S3Config
from storguard.chaos.controller import ChaosController
from storguard.integrity.validator import IntegrityValidator
from storguard.quality_gate.gate import GateThresholds, QualityGate
from storguard.snapshot.service import SnapshotService


# ─── Config ───────────────────────────────────────────────────────────────────

def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


S3_ENDPOINT = _env("MINIO_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = _env("MINIO_ROOT_USER", "storguard")
S3_SECRET_KEY = _env("MINIO_ROOT_PASSWORD", "storguard_secret_123")
SECONDARY_S3_ENDPOINT = _env("MINIO_SECONDARY_ENDPOINT", "http://localhost:9200")

_MINIO_CONTAINERS = [
    "storguard-minio1",
    "storguard-minio2",
    "storguard-minio3",
    "storguard-minio4",
]


# ─── Session-scoped clients ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def s3_config() -> S3Config:
    return S3Config(
        endpoint=S3_ENDPOINT,
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
    )


@pytest.fixture(scope="session")
def s3(s3_config: S3Config) -> S3Client:
    return S3Client(s3_config)


@pytest.fixture(scope="session")
def secondary_s3_config() -> S3Config:
    return S3Config(
        endpoint=SECONDARY_S3_ENDPOINT,
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
    )


@pytest.fixture(scope="session")
def secondary_s3(secondary_s3_config: S3Config) -> S3Client:
    return S3Client(secondary_s3_config)


@pytest.fixture(scope="session")
def linux() -> LinuxClient:
    return LinuxClient()


@pytest.fixture(scope="session")
def docker_client() -> Generator[DockerClient, None, None]:
    client = DockerClient()
    yield client
    client.close()


@pytest.fixture(scope="session")
def chaos(docker_client: DockerClient) -> Generator[ChaosController, None, None]:
    controller = ChaosController(docker_client)
    yield controller
    controller.restore_all()   # safety net


@pytest.fixture(scope="session")
def integrity(s3: S3Client) -> IntegrityValidator:
    return IntegrityValidator(s3)


@pytest.fixture(scope="session")
def gate() -> QualityGate:
    return QualityGate(GateThresholds())


@pytest.fixture(scope="session")
def snapshots(s3: S3Client) -> SnapshotService:
    return SnapshotService(s3)


# ─── Test-scoped bucket (parallel-safe, auto-cleaned) ────────────────────────

@pytest.fixture()
def test_bucket(s3: S3Client) -> Generator[str, None, None]:
    bucket = f"storguard-test-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(bucket)
    yield bucket
    try:
        for key in s3.list_objects(bucket):
            s3.delete_object(bucket, key)
        s3.delete_bucket(bucket)
    except Exception:
        pass


@pytest.fixture()
def replication_bucket(s3: S3Client, secondary_s3: S3Client) -> Generator[str, None, None]:
    """Same-named bucket provisioned on both the primary and secondary site."""
    bucket = f"storguard-repl-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(bucket)
    secondary_s3.create_bucket(bucket)
    yield bucket
    for client in (s3, secondary_s3):
        try:
            for key in client.list_objects(bucket):
                client.delete_object(bucket, key)
            client.delete_bucket(bucket)
        except Exception:
            pass


# ─── Allure auto-attach on failure ───────────────────────────────────────────

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    # 1. Attach open ports from Linux client
    try:
        client = item.funcargs.get("linux")
        if client:
            result = client.get_open_ports()
            allure.attach(
                result.stdout,
                name="open-ports-at-failure",
                attachment_type=allure.attachment_type.TEXT,
            )
    except Exception:
        pass

    # 2. AI log analysis — attach AI anomaly report for each MinIO node on failure
    # Uses a short 30s timeout so teardown never blocks the full suite.
    try:
        docker = item.funcargs.get("docker_client")
        if docker:
            from storguard.ai.log_analyzer import LogAnalyzer
            from storguard.ai.ollama_client import OllamaClient, OllamaConfig

            ai_client = OllamaClient(OllamaConfig(timeout_seconds=30))
            if ai_client.is_available():
                analyzer = LogAnalyzer(ai_client)
                for container in _MINIO_CONTAINERS:
                    try:
                        logs = docker.get_logs(container, tail=50)
                        analysis = analyzer.analyze(logs, container)
                        if analysis.anomalies or analysis.severity in ("high", "critical"):
                            allure.attach(
                                analysis.format_report(),
                                name=f"ai-log-analysis-{container}",
                                attachment_type=allure.attachment_type.TEXT,
                            )
                    except Exception:
                        pass
            ai_client.close()
    except Exception:
        pass
