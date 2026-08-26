"""L2 Component — LogAnalyzer: pattern detection, AI path, offline fallback.

All tests use mocked OllamaClient — no Ollama required.
"""

from __future__ import annotations

import allure
import pytest

from storguard.ai.log_analyzer import LogAnalyzer


# ─── Pattern detection (parametrized) ────────────────────────────────────────

_PATTERN_CASES = [
    pytest.param(
        "2024-01-01 FATAL: storage corruption detected",
        ["fatal", "corruption", "data"],
        id="fatal-corruption",
    ),
    pytest.param(
        "write error: no space left on device ENOSPC",
        ["disk", "space", "exhaustion"],
        id="disk-full-enospc",
    ),
    pytest.param(
        "connection refused on 127.0.0.1:9000",
        ["network", "connectivity", "failure"],
        id="connection-refused",
    ),
    pytest.param(
        "out of memory: kill process 1234",
        ["memory", "oom", "pressure"],
        id="oom-kill",
    ),
    pytest.param(
        "storage timeout after 5000ms exceeded threshold",
        ["timeout", "1", "s"],
        id="timeout-over-1s",
    ),
]

_CLEAN_LOG_CASES = [
    pytest.param("INFO: object stored successfully in 45ms", id="normal-info"),
    pytest.param("DEBUG: heartbeat OK", id="debug-heartbeat"),
    pytest.param("", id="empty-string"),
    pytest.param("a" * 10000, id="long-noise-string"),
]


@allure.feature("AI — Log Analyzer")
@allure.story("Pattern Detection")
@pytest.mark.unit
class TestLogAnalyzerPatternDetection:

    @allure.title("Detects critical pattern: {log_line}")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.parametrize("log_line,expected_keywords", _PATTERN_CASES)
    def test_detects_known_error_pattern(self, offline_client, log_line, expected_keywords):
        with allure.step(f"Run _detect_patterns on: {log_line!r:.60}"):
            analyzer = LogAnalyzer(offline_client)
            anomalies = analyzer._detect_patterns(log_line)

        with allure.step("Assert at least one anomaly returned"):
            assert len(anomalies) >= 1

        with allure.step(f"Assert label text contains one of {expected_keywords}"):
            combined = " ".join(anomalies).lower()
            assert any(kw in combined for kw in expected_keywords), (
                f"Expected one of {expected_keywords} in anomalies: {anomalies}"
            )

    @allure.title("Clean log produces no anomalies: {log_line!r:.40}")
    @pytest.mark.parametrize("log_line", _CLEAN_LOG_CASES)
    def test_clean_log_no_anomalies(self, offline_client, log_line):
        with allure.step("Run _detect_patterns on clean log"):
            analyzer = LogAnalyzer(offline_client)
            anomalies = analyzer._detect_patterns(log_line)

        with allure.step("Assert empty anomaly list"):
            assert anomalies == []


@allure.feature("AI — Log Analyzer")
@allure.story("Offline Fallback")
@pytest.mark.unit
class TestLogAnalyzerOfflineFallback:

    @allure.title("Rule-based fallback sets ai_available=False")
    @allure.severity(allure.severity_level.NORMAL)
    def test_offline_sets_ai_available_false(self, offline_client):
        with allure.step("Analyze logs with offline client"):
            result = LogAnalyzer(offline_client).analyze("FATAL: disk full", "test-node")

        with allure.step("Verify ai_available is False"):
            assert result.ai_available is False

    @allure.title("Severity is elevated when critical patterns found offline")
    def test_severity_elevated_on_critical_pattern(self, offline_client):
        with allure.step("Analyze critical log offline"):
            result = LogAnalyzer(offline_client).analyze("FATAL: disk full", "test-node")

        with allure.step("Verify severity is medium/high/critical"):
            assert result.severity in ("medium", "high", "critical")

    @allure.title("Container name is preserved in result")
    def test_container_name_preserved(self, offline_client):
        with allure.step("Analyze log for storguard-minio3"):
            result = LogAnalyzer(offline_client).analyze("INFO: ok", "storguard-minio3")

        with allure.step("Assert container name matches"):
            assert result.container == "storguard-minio3"

    @allure.title("Clean logs produce low severity and is_healthy=True")
    def test_clean_logs_low_severity(self, offline_client):
        with allure.step("Analyze clean INFO log"):
            result = LogAnalyzer(offline_client).analyze("INFO: all operations succeeded", "minio1")

        with allure.step("Assert severity=low and is_healthy=True"):
            assert result.severity == "low"
            assert result.is_healthy is True

    @allure.title("Empty log string does not raise")
    @pytest.mark.negative
    def test_empty_log_string(self, offline_client):
        with allure.step("Analyze empty string"):
            result = LogAnalyzer(offline_client).analyze("", "minio1")

        with allure.step("Assert result is returned without exception"):
            assert result is not None
            assert result.severity == "low"


@allure.feature("AI — Log Analyzer")
@allure.story("AI Response Parsing")
@pytest.mark.unit
class TestLogAnalyzerAIPath:

    @allure.title("Parses well-formed AI JSON response into LogAnalysis")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_parses_valid_ai_response(self, online_client_factory):
        payload = {
            "severity": "high",
            "anomalies": ["connection refused on port 9000"],
            "root_cause": "minio2 container stopped unexpectedly",
            "recommendations": ["restart minio2", "check Docker logs"],
        }

        with allure.step("Build online mock client with valid AI payload"):
            client = online_client_factory.online(payload)

        with allure.step("Analyze connection error log"):
            result = LogAnalyzer(client).analyze("connection refused", "storguard-gateway")

        with allure.step("Assert severity=high and ai_available=True"):
            assert result.severity == "high"
            assert result.ai_available is True

        with allure.step("Assert anomaly content and recommendation count"):
            assert "connection refused" in result.anomalies[0]
            assert len(result.recommendations) == 2

    @allure.title("Falls back to rule-based when AI returns malformed JSON")
    @pytest.mark.negative
    def test_malformed_ai_response_falls_back(self, online_client_factory):
        with allure.step("Build client returning malformed JSON"):
            client = online_client_factory.malformed()

        with allure.step("Analyze logs (should not raise)"):
            result = LogAnalyzer(client).analyze("FATAL: crash", "minio1")

        with allure.step("Assert result has a valid severity"):
            assert result is not None
            assert result.severity in ("low", "medium", "high", "critical")

    @allure.title("format_report includes container name and severity")
    def test_format_report_contains_required_sections(self, offline_client):
        with allure.step("Analyze mixed error log"):
            result = LogAnalyzer(offline_client).analyze(
                "FATAL: disk full\nconnection refused", "minio1"
            )

        with allure.step("Generate text report"):
            report = result.format_report()

        with allure.step("Assert report contains container name and severity label"):
            assert "minio1" in report
            assert any(s in report for s in ("SEVERITY", "Severity", "severity"))
