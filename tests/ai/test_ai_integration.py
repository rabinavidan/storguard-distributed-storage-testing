"""L3 Integration — AI modules against a live Ollama instance.

All tests auto-skip when Ollama is offline or the configured model is not pulled.
Run with: pytest tests/ai/test_ai_integration.py -m ai -v
"""

from __future__ import annotations

import allure
import pytest

from storguard.ai.chaos_advisor import ChaosAdvisor
from storguard.ai.log_analyzer import LogAnalyzer
from storguard.ai.ollama_client import OllamaClient, OllamaConfig
from storguard.ai.report_summarizer import ReportSummarizer

_KNOWN_SCENARIOS = {"node-failure", "network-latency", "packet-loss", "disk-pressure"}
_SEVERITY_VALUES = {"low", "medium", "high", "critical"}


@allure.feature("AI — Integration")
@allure.story("Ollama Runtime")
@pytest.mark.ai
@pytest.mark.timeout(600)
class TestOllamaRuntime:

    @allure.title("Ollama server is reachable at localhost:11434")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_ollama_reachable(self, require_ollama):
        with allure.step("Call is_available() on default OllamaClient"):
            result = OllamaClient().is_available()
        with allure.step("Assert True"):
            assert result is True

    @allure.title("list_models returns a non-empty list")
    def test_list_models_returns_list(self, require_ollama):
        with allure.step("Call list_models()"):
            models = OllamaClient().list_models()
        with allure.step("Assert list is non-empty"):
            assert isinstance(models, list)
            assert len(models) > 0

    @allure.title("Configured model is present in the model list")
    def test_configured_model_is_installed(self, require_ollama):
        with allure.step("Read configured model name"):
            model = OllamaConfig().model
        with allure.step("Fetch installed model list"):
            installed = OllamaClient().list_models()
        with allure.step(f"Assert '{model}' is in installed list"):
            assert any(model in m for m in installed), (
                f"Model '{model}' not in installed list: {installed}"
            )

    @allure.title("generate() returns non-empty content with positive duration_ms")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_generate_returns_content(self, require_ollama):
        with allure.step("Send single-word prompt to Ollama"):
            resp = OllamaClient().generate("Reply with the single word: PONG")
        with allure.step("Assert content non-empty and duration positive"):
            assert len(resp.content) > 0
            assert resp.duration_ms > 0

    @allure.title("generate() response is coherent for a factual prompt")
    def test_generate_coherent_response(self, require_ollama):
        with allure.step("Ask for the capital of France"):
            resp = OllamaClient().generate(
                "What is the capital of France? Reply with one word only."
            )
        with allure.step("Assert 'paris' appears in response (case-insensitive)"):
            assert "paris" in resp.content.lower()


@allure.feature("AI — Integration")
@allure.story("Log Analyzer — Live AI")
@pytest.mark.ai
@pytest.mark.timeout(600)
class TestLogAnalyzerIntegration:

    @allure.title("Analyzes healthy MinIO logs and returns valid severity")
    @allure.severity(allure.severity_level.NORMAL)
    def test_healthy_logs_severity_in_range(self, require_ollama):
        with allure.step("Build 5-line healthy log corpus"):
            logs = "2024-01-01T00:00:00Z INFO: object stored OK\n" * 5

        with allure.step("Analyze logs with live Ollama client"):
            result = LogAnalyzer(OllamaClient()).analyze(logs, "storguard-minio1")

        with allure.step("Assert ai_available=True and severity in valid range"):
            assert result.ai_available is True
            assert result.severity in _SEVERITY_VALUES

    @allure.title("Analyzes error logs and flags elevated severity")
    def test_error_logs_elevated_severity(self, require_ollama):
        with allure.step("Build multi-error log corpus"):
            logs = (
                "FATAL: disk full — no space left\n"
                "connection refused on 9000\n"
                "out of memory: kill process 42\n"
            )

        with allure.step("Analyze logs with live Ollama"):
            result = LogAnalyzer(OllamaClient()).analyze(logs, "storguard-minio2")

        with allure.step("Assert severity is medium/high/critical"):
            assert result.ai_available is True
            assert result.severity in ("medium", "high", "critical")

    @allure.title("Container name is preserved on live AI path")
    def test_container_name_preserved(self, require_ollama):
        with allure.step("Analyze minimal log for storguard-minio3"):
            result = LogAnalyzer(OllamaClient()).analyze("INFO: ok", "storguard-minio3")

        with allure.step("Assert container field matches"):
            assert result.container == "storguard-minio3"


@allure.feature("AI — Integration")
@allure.story("Chaos Advisor — Live AI")
@pytest.mark.ai
@pytest.mark.timeout(600)
class TestChaosAdvisorIntegration:

    @allure.title("Recommends at least one known scenario with live metrics")
    @allure.severity(allure.severity_level.NORMAL)
    def test_recommends_known_scenarios(self, require_ollama, metrics_healthy):
        with allure.step("Call recommend() with healthy WorkloadMetrics"):
            recs = ChaosAdvisor(OllamaClient()).recommend(metrics=metrics_healthy)

        with allure.step("Assert at least one recommendation"):
            assert len(recs) >= 1

        with allure.step(f"Assert all scenarios are in {_KNOWN_SCENARIOS}"):
            assert all(r.scenario in _KNOWN_SCENARIOS for r in recs)

    @allure.title("Recommendations include rationale and valid priority")
    def test_recommendations_have_required_fields(self, require_ollama, metrics_healthy):
        with allure.step("Get live recommendations"):
            recs = ChaosAdvisor(OllamaClient()).recommend(metrics=metrics_healthy)

        with allure.step("Assert each recommendation has rationale and priority"):
            for rec in recs:
                assert rec.rationale
                assert rec.priority in ("low", "medium", "high", "critical")


@allure.feature("AI — Integration")
@allure.story("Report Summarizer — Live AI")
@pytest.mark.ai
@pytest.mark.timeout(600)
class TestReportSummarizerIntegration:

    @allure.title("Generates headline and summary for healthy metrics")
    @allure.severity(allure.severity_level.NORMAL)
    def test_summarizes_healthy_metrics(self, require_ollama, metrics_healthy):
        with allure.step("Summarize healthy metrics with live Ollama"):
            narrative = ReportSummarizer(OllamaClient()).summarize_metrics(metrics_healthy)

        with allure.step("Assert ai_available=True, headline and summary non-empty"):
            assert narrative.ai_available is True
            assert narrative.headline
            assert narrative.summary

    @allure.title("format_report produces valid markdown for live narrative")
    def test_format_report_valid_markdown(self, require_ollama, metrics_healthy):
        with allure.step("Get live narrative and format as markdown"):
            narrative = ReportSummarizer(OllamaClient()).summarize_metrics(metrics_healthy)
            report = narrative.format_report()

        with allure.step("Assert report starts with '#' and has substance"):
            assert report.startswith("#")
            assert len(report) > 50
