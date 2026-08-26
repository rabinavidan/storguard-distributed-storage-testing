"""Shared fixtures and builders for the AI test layer.

Layer contract:
    conftest.py          ← factories + session-scoped Ollama availability
    test_ollama_client   ← L1 unit  : config, connectivity, context manager
    test_log_analyzer    ← L2 component : pattern detection, AI parse, fallback
    test_report_summarizer ← L2 component : narrative generation, schema
    test_chaos_advisor   ← L2 component : recommendation engine
    test_ai_integration  ← L3 integration : live Ollama end-to-end
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from storguard.ai.ollama_client import OllamaClient, OllamaConfig, OllamaResponse
from storguard.models import WorkloadMetrics


# ─── Test-data builders ───────────────────────────────────────────────────────

class OllamaClientBuilder:
    """Factory that constructs pre-configured mock OllamaClient instances."""

    @staticmethod
    def online(response_payload: Dict[str, Any], model: str = "gemma4:26b") -> MagicMock:
        client = MagicMock(spec=OllamaClient)
        client.is_available.return_value = True
        client.generate.return_value = OllamaResponse(
            content=json.dumps(response_payload),
            model=model,
            duration_ms=50.0,
        )
        return client

    @staticmethod
    def offline() -> MagicMock:
        client = MagicMock(spec=OllamaClient)
        client.is_available.return_value = False
        return client

    @staticmethod
    def malformed(raw_content: str = "not-json {{{{") -> MagicMock:
        """Returns a client whose AI response cannot be parsed as JSON."""
        client = MagicMock(spec=OllamaClient)
        client.is_available.return_value = True
        client.generate.return_value = OllamaResponse(
            content=raw_content,
            model="gemma4:26b",
            duration_ms=30.0,
        )
        return client


class MetricsBuilder:
    """Factory for WorkloadMetrics test data."""

    @staticmethod
    def healthy() -> WorkloadMetrics:
        return WorkloadMetrics(
            total_operations=50,
            successful_operations=49,
            failed_operations=1,
            duration_seconds=5.0,
            throughput_mbps=67.3,
            latency_ms_min=20.0,
            latency_ms_avg=136.0,
            latency_ms_max=250.0,
            latency_ms_p95=188.0,
            latency_ms_p99=220.0,
            error_rate_percent=2.0,
        )

    @staticmethod
    def degraded() -> WorkloadMetrics:
        return WorkloadMetrics(
            total_operations=50,
            successful_operations=30,
            failed_operations=20,
            duration_seconds=15.0,
            throughput_mbps=8.1,
            latency_ms_min=200.0,
            latency_ms_avg=950.0,
            latency_ms_max=3000.0,
            latency_ms_p95=2500.0,
            latency_ms_p99=2900.0,
            error_rate_percent=40.0,
        )

    @staticmethod
    def zero_operations() -> WorkloadMetrics:
        return WorkloadMetrics(
            total_operations=0,
            successful_operations=0,
            failed_operations=0,
            duration_seconds=0.0,
            throughput_mbps=0.0,
            latency_ms_min=0.0,
            latency_ms_avg=0.0,
            latency_ms_max=0.0,
            latency_ms_p95=0.0,
            latency_ms_p99=0.0,
            error_rate_percent=0.0,
        )


# ─── Pytest fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def online_client_factory():
    """Returns the OllamaClientBuilder so tests can create multiple variants."""
    return OllamaClientBuilder


@pytest.fixture
def offline_client() -> MagicMock:
    return OllamaClientBuilder.offline()


@pytest.fixture
def metrics_healthy() -> WorkloadMetrics:
    return MetricsBuilder.healthy()


@pytest.fixture
def metrics_degraded() -> WorkloadMetrics:
    return MetricsBuilder.degraded()


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    """Session-scoped: probe Ollama once, share result across all integration tests."""
    client = OllamaClient()
    available = client.is_available()
    client.close()
    return available


@pytest.fixture(scope="session")
def ollama_model_installed(ollama_available) -> bool:
    """Session-scoped: confirm the configured model is actually pulled."""
    if not ollama_available:
        return False
    client = OllamaClient()
    model = OllamaConfig().model
    installed = any(model in m for m in client.list_models())
    client.close()
    return installed


@pytest.fixture
def require_ollama(ollama_available, ollama_model_installed):
    """Skip the test if Ollama is offline or model not installed."""
    if not ollama_available:
        pytest.skip("Ollama not running at localhost:11434")
    if not ollama_model_installed:
        pytest.skip(f"Model '{OllamaConfig().model}' not pulled — run: ollama pull {OllamaConfig().model}")
