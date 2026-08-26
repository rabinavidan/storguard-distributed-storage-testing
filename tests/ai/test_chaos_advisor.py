"""L2 Component — ChaosAdvisor: recommendation engine, AI parse, offline fallback.

All tests use mocked OllamaClient — no Ollama required.
"""

from __future__ import annotations

from typing import Any, Dict

import allure
import pytest

from storguard.ai.chaos_advisor import ChaosAdvisor, ChaosRecommendation

_KNOWN_SCENARIOS = {"node-failure", "network-latency", "packet-loss", "disk-pressure"}

_CLUSTER_STATE_CASES = [
    pytest.param({"nodes": 4, "healthy": 4, "disk_usage_percent": 20}, id="healthy-cluster"),
    pytest.param({"nodes": 4, "healthy": 3, "disk_usage_percent": 65}, id="one-node-down"),
    pytest.param({"nodes": 4, "healthy": 4, "disk_usage_percent": 88}, id="high-disk-pressure"),
    pytest.param({}, id="empty-state"),
]


@allure.feature("AI — Chaos Advisor")
@allure.story("Offline Fallback")
@pytest.mark.unit
class TestChaosAdvisorOffline:

    @allure.title("Returns at least 3 default recommendations when offline")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_returns_minimum_recommendations_offline(self, offline_client):
        with allure.step("Call recommend() with offline client"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step("Assert at least 3 recommendations returned"):
            assert len(recs) >= 3

    @allure.title("Default recommendations include node-failure scenario")
    def test_node_failure_in_defaults(self, offline_client):
        with allure.step("Collect default scenario names"):
            scenarios = {r.scenario for r in ChaosAdvisor(offline_client).recommend()}

        with allure.step("Assert 'node-failure' is in default set"):
            assert "node-failure" in scenarios

    @allure.title("Recommendations are ChaosRecommendation instances")
    def test_recommendation_types(self, offline_client):
        with allure.step("Get recommendations"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step("Assert all items are ChaosRecommendation"):
            assert all(isinstance(r, ChaosRecommendation) for r in recs)

    @allure.title("Offline recommendations with various cluster states still returns list")
    @pytest.mark.parametrize("cluster_state", _CLUSTER_STATE_CASES)
    def test_with_various_cluster_states(self, offline_client, cluster_state: Dict[str, Any]):
        with allure.step(f"Recommend with cluster_state={cluster_state}"):
            recs = ChaosAdvisor(offline_client).recommend(cluster_state=cluster_state)

        with allure.step("Assert non-empty list returned"):
            assert len(recs) >= 1

    @allure.title("Offline recommendations with degraded metrics still returns list")
    def test_with_degraded_metrics(self, offline_client, metrics_degraded):
        with allure.step("Recommend with degraded WorkloadMetrics"):
            recs = ChaosAdvisor(offline_client).recommend(metrics=metrics_degraded)

        with allure.step("Assert list with ChaosRecommendation items"):
            assert isinstance(recs, list)
            assert len(recs) >= 1


@allure.feature("AI — Chaos Advisor")
@allure.story("AI Response Parsing")
@pytest.mark.unit
class TestChaosAdvisorAIPath:

    @allure.title("Parses valid AI recommendation with all required fields")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_parses_valid_ai_recommendation(self, online_client_factory, metrics_healthy):
        payload = {
            "recommendations": [
                {
                    "scenario": "network-latency",
                    "rationale": "high P99 suggests retry sensitivity",
                    "expected_impact": "latency increases, retries absorb failures",
                    "priority": "high",
                    "parameters": {"latency_ms": 500},
                }
            ]
        }

        with allure.step("Build online client with single-item recommendation payload"):
            client = online_client_factory.online(payload)

        with allure.step("Call recommend() with healthy metrics"):
            recs = ChaosAdvisor(client).recommend(metrics=metrics_healthy)

        with allure.step("Assert exactly one recommendation returned"):
            assert len(recs) == 1

        with allure.step("Assert scenario, priority and parameter values"):
            assert recs[0].scenario == "network-latency"
            assert recs[0].priority == "high"
            assert recs[0].parameters["latency_ms"] == 500

    @allure.title("Falls back to defaults when AI returns malformed JSON")
    @pytest.mark.negative
    def test_malformed_ai_response_falls_back_to_defaults(self, online_client_factory):
        with allure.step("Build client returning malformed JSON"):
            client = online_client_factory.malformed()

        with allure.step("Call recommend() — expect no raise"):
            recs = ChaosAdvisor(client).recommend()

        with allure.step("Assert at least one fallback recommendation"):
            assert len(recs) >= 1

    @allure.title("Multiple AI recommendations are all parsed")
    def test_multiple_ai_recommendations(self, online_client_factory):
        payload = {
            "recommendations": [
                {
                    "scenario": "node-failure",
                    "rationale": "single point of failure",
                    "expected_impact": "quorum still holds with 3 nodes",
                    "priority": "high",
                    "parameters": {},
                },
                {
                    "scenario": "packet-loss",
                    "rationale": "network instability test",
                    "expected_impact": "retries increase, some failures",
                    "priority": "medium",
                    "parameters": {"loss_percent": 30},
                },
            ]
        }

        with allure.step("Build client with two-item recommendation payload"):
            client = online_client_factory.online(payload)

        with allure.step("Call recommend()"):
            recs = ChaosAdvisor(client).recommend()

        with allure.step("Assert both recommendations were parsed"):
            assert len(recs) == 2


@allure.feature("AI — Chaos Advisor")
@allure.story("Recommendation Format")
@pytest.mark.unit
class TestChaosRecommendationFormat:

    @allure.title("format() includes scenario name")
    def test_format_includes_scenario(self, offline_client):
        with allure.step("Get default recommendations"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step("Assert each rec's scenario appears in its format() output"):
            for rec in recs:
                assert rec.scenario in rec.format()

    @allure.title("format() includes priority in uppercase")
    def test_format_includes_priority_uppercase(self, offline_client):
        with allure.step("Get default recommendations"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step("Assert each rec's priority.upper() appears in format()"):
            for rec in recs:
                assert rec.priority.upper() in rec.format()

    @allure.title("format() includes Rationale section")
    def test_format_includes_rationale(self, offline_client):
        with allure.step("Get default recommendations"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step("Assert 'Rationale' label is in each format() output"):
            for rec in recs:
                assert "Rationale" in rec.format()

    @allure.title("All default scenarios are within the known scenario set")
    def test_default_scenarios_are_known(self, offline_client):
        with allure.step("Get default recommendations"):
            recs = ChaosAdvisor(offline_client).recommend()

        with allure.step(f"Assert every scenario is one of {_KNOWN_SCENARIOS}"):
            for rec in recs:
                assert rec.scenario in _KNOWN_SCENARIOS, (
                    f"Unknown scenario '{rec.scenario}' — add it to _KNOWN_SCENARIOS"
                )
