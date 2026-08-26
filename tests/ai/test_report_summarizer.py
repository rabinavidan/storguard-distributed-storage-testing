"""L2 Component — ReportSummarizer: narrative generation, schema, offline fallback.

All tests use mocked OllamaClient — no Ollama required.
"""

from __future__ import annotations

import allure
import pytest

from storguard.ai.report_summarizer import ReportSummarizer
from tests.ai.conftest import MetricsBuilder


@allure.feature("AI — Report Summarizer")
@allure.story("Offline Fallback")
@pytest.mark.unit
class TestReportSummarizerOffline:

    @allure.title("Offline narrative sets ai_available=False")
    @allure.severity(allure.severity_level.NORMAL)
    def test_offline_sets_ai_available_false(self, offline_client, metrics_healthy):
        with allure.step("Summarize healthy metrics with offline client"):
            narrative = ReportSummarizer(offline_client).summarize_metrics(metrics_healthy)

        with allure.step("Assert ai_available=False"):
            assert narrative.ai_available is False

    @allure.title("Offline headline references throughput or workload label")
    def test_offline_headline_references_throughput(self, offline_client, metrics_healthy):
        with allure.step("Generate narrative offline"):
            narrative = ReportSummarizer(offline_client).summarize_metrics(metrics_healthy)

        with allure.step("Assert headline contains throughput value or 'Workload' label"):
            assert "67.3" in narrative.headline or "Workload" in narrative.headline

    @allure.title("Zero-operation metrics do not raise")
    @pytest.mark.negative
    def test_zero_operations_no_exception(self, offline_client):
        with allure.step("Build zero-operation WorkloadMetrics"):
            metrics = MetricsBuilder.zero_operations()

        with allure.step("Summarize — expect no exception"):
            narrative = ReportSummarizer(offline_client).summarize_metrics(metrics)

        with allure.step("Assert result is not None"):
            assert narrative is not None

    @allure.title("Degraded metrics produce a non-empty headline offline")
    def test_degraded_metrics_offline(self, offline_client, metrics_degraded):
        with allure.step("Summarize degraded metrics offline"):
            narrative = ReportSummarizer(offline_client).summarize_metrics(metrics_degraded)

        with allure.step("Assert result has a non-empty headline"):
            assert narrative is not None
            assert narrative.headline


@allure.feature("AI — Report Summarizer")
@allure.story("AI Response Parsing")
@pytest.mark.unit
class TestReportSummarizerAIPath:

    @allure.title("Parses well-formed AI response into AITestNarrative")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_parses_valid_ai_response(self, online_client_factory, metrics_healthy):
        payload = {
            "headline": "67 MB/s throughput with 2% error rate",
            "summary": "The cluster processed 50 operations in 5s.",
            "key_findings": ["throughput within SLA", "P95 latency acceptable"],
            "risk_assessment": "low — no threshold violations",
        }

        with allure.step("Build online client with valid narrative payload"):
            client = online_client_factory.online(payload)

        with allure.step("Summarize healthy metrics with AI client"):
            narrative = ReportSummarizer(client).summarize_metrics(metrics_healthy)

        with allure.step("Assert ai_available=True and headline contains '67'"):
            assert narrative.ai_available is True
            assert "67" in narrative.headline

        with allure.step("Assert key_findings has 2 items"):
            assert len(narrative.key_findings) == 2

    @allure.title("Falls back gracefully when AI returns malformed JSON")
    @pytest.mark.negative
    def test_malformed_response_falls_back(self, online_client_factory, metrics_healthy):
        with allure.step("Build client returning malformed JSON"):
            client = online_client_factory.malformed()

        with allure.step("Summarize metrics — expect no exception"):
            narrative = ReportSummarizer(client).summarize_metrics(metrics_healthy)

        with allure.step("Assert result has a non-empty headline"):
            assert narrative is not None
            assert narrative.headline


@allure.feature("AI — Report Summarizer")
@allure.story("Report Schema")
@pytest.mark.unit
class TestReportSummarizerSchema:

    @allure.title("format_report starts with markdown heading (#)")
    def test_format_report_starts_with_heading(self, offline_client, metrics_healthy):
        with allure.step("Generate narrative and format as markdown"):
            report = ReportSummarizer(offline_client).summarize_metrics(metrics_healthy).format_report()

        with allure.step("Assert report starts with '#'"):
            assert report.startswith("#")

    @allure.title("format_report contains Key Findings section")
    def test_format_report_has_key_findings(self, offline_client, metrics_healthy):
        with allure.step("Format report"):
            report = ReportSummarizer(offline_client).summarize_metrics(metrics_healthy).format_report()

        with allure.step("Assert 'Key Findings:' present"):
            assert "Key Findings:" in report

    @allure.title("format_report contains Risk section")
    def test_format_report_has_risk(self, offline_client, metrics_healthy):
        with allure.step("Format report"):
            report = ReportSummarizer(offline_client).summarize_metrics(metrics_healthy).format_report()

        with allure.step("Assert 'Risk:' present"):
            assert "Risk:" in report
